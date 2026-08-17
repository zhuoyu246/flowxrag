"""Enterprise memory service.

Memory is split into durable saved memories and softer chat-history recall.
Saved memories are structured, auditable and user-manageable. Current user
messages always override older memory when they conflict.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user import User
from backend.models.user_memory import UserMemory

ANON_SCOPE = "anonymous"
ACTIVE = "active"
CANDIDATE = "candidate"
REJECTED = "rejected"


def scope_for_user(user: User | None) -> tuple[int | None, str]:
    if user is None:
        return None, ANON_SCOPE
    return user.id, f"user:{user.id}"


async def list_memories(
    db: AsyncSession,
    user: User | None,
    *,
    status: str | None = ACTIVE,
    include_inactive: bool = False,
    limit: int = 100,
) -> list[UserMemory]:
    user_id, scope_key = scope_for_user(user)
    stmt = (
        select(UserMemory)
        .where(UserMemory.user_id.is_(None) if user_id is None else UserMemory.user_id == user_id)
        .where(UserMemory.scope_key == scope_key)
        .order_by(UserMemory.status.asc(), UserMemory.importance.desc(), UserMemory.updated_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(UserMemory.status == status)
    if not include_inactive:
        stmt = stmt.where(UserMemory.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_memory(
    db: AsyncSession,
    user: User | None,
    content: str,
    *,
    category: str = "preference",
    memory_key: str | None = None,
    status: str = ACTIVE,
    source: str = "manual",
    confidence: float = 1.0,
    importance: float = 0.8,
    source_session_id: int | None = None,
    source_message_id: int | None = None,
    is_sensitive: bool = False,
    extra: dict | None = None,
) -> UserMemory:
    user_id, scope_key = scope_for_user(user)
    normalized = normalize_memory(content)
    key = normalize_key(memory_key or infer_memory_key(category, normalized))

    existing = await _find_by_key(db, user_id, scope_key, key, status=None)
    if existing and existing.status != REJECTED:
        next_status = existing.status if existing.status == ACTIVE and status == CANDIDATE else status
        existing.content = normalized
        existing.category = category or existing.category
        existing.status = next_status
        existing.source = source
        existing.confidence = max(existing.confidence, confidence)
        existing.importance = max(existing.importance, importance)
        existing.source_session_id = source_session_id or existing.source_session_id
        existing.source_message_id = source_message_id or existing.source_message_id
        existing.is_sensitive = is_sensitive
        existing.is_active = True
        existing.extra = {**(existing.extra or {}), **(extra or {})}
        await db.flush()
        return existing

    memory = UserMemory(
        user_id=user_id,
        scope_key=scope_key,
        memory_key=key,
        category=category or "preference",
        content=normalized,
        status=status,
        source=source,
        source_session_id=source_session_id,
        source_message_id=source_message_id,
        confidence=confidence,
        importance=importance,
        is_sensitive=is_sensitive,
        is_active=True,
        extra=extra or {},
    )
    db.add(memory)
    await db.flush()
    return memory


async def update_memory(
    db: AsyncSession,
    memory: UserMemory,
    *,
    content: str | None = None,
    category: str | None = None,
    memory_key: str | None = None,
    status: str | None = None,
    is_active: bool | None = None,
) -> UserMemory:
    if content is not None:
        memory.content = normalize_memory(content)
    if category is not None:
        memory.category = category
    if memory_key is not None:
        memory.memory_key = normalize_key(memory_key)
    if status is not None:
        memory.status = status
        memory.is_active = status != REJECTED
    if is_active is not None:
        memory.is_active = is_active
    await db.flush()
    return memory


async def get_memory(db: AsyncSession, memory_id: int, user: User | None) -> UserMemory | None:
    user_id, scope_key = scope_for_user(user)
    stmt = select(UserMemory).where(UserMemory.id == memory_id, UserMemory.scope_key == scope_key)
    stmt = stmt.where(UserMemory.user_id.is_(None) if user_id is None else UserMemory.user_id == user_id)
    return await db.scalar(stmt)


async def delete_memory(db: AsyncSession, memory_id: int, user: User | None) -> bool:
    memory = await get_memory(db, memory_id, user)
    if memory is None:
        return False
    memory.status = REJECTED
    memory.is_active = False
    await db.flush()
    return True


async def deactivate_all_memories(db: AsyncSession, user: User | None) -> int:
    user_id, scope_key = scope_for_user(user)
    stmt = update(UserMemory).where(UserMemory.scope_key == scope_key)
    stmt = stmt.where(UserMemory.user_id.is_(None) if user_id is None else UserMemory.user_id == user_id)
    result = await db.execute(stmt.values(status=REJECTED, is_active=False))
    await db.flush()
    return int(result.rowcount or 0)


async def maybe_store_memories_from_turn(
    db: AsyncSession,
    user: User | None,
    question: str,
    answer: str | None = None,
    *,
    session_id: int | None = None,
    message_id: int | None = None,
) -> list[UserMemory]:
    candidates = await extract_memory_candidates(question)
    stored = []
    for candidate in candidates:
        if _looks_ephemeral(candidate["content"]) or _is_sensitive(candidate["content"]):
            continue
        if candidate["confidence"] < 0.75:
            continue
        status = ACTIVE
        stored.append(
            await create_memory(
                db,
                user,
                candidate["content"],
                category=candidate["category"],
                memory_key=candidate["memory_key"],
                status=status,
                source=candidate["source"],
                confidence=candidate["confidence"],
                importance=candidate["importance"],
                source_session_id=session_id,
                source_message_id=message_id,
                extra={"reason": candidate.get("reason", "")},
            )
        )
    return stored


async def format_memory_context(db: AsyncSession | None, user: User | None, limit: int = 12) -> str:
    if db is None:
        return ""
    memories = await list_memories(db, user, status=ACTIVE, limit=limit)
    if not memories:
        return ""

    now = datetime.now(timezone.utc)
    lines = []
    for memory in memories:
        memory.use_count += 1
        memory.last_used_at = now
        lines.append(
            f"- key={memory.memory_key}; category={memory.category}; "
            f"confidence={memory.confidence:.2f}; {memory.content}"
        )
    await db.flush()
    return "\n".join(lines)


async def extract_memory_candidates(text: str) -> list[dict[str, Any]]:
    normalized = normalize_memory(text)
    if not normalized:
        return []
    if _looks_like_question(normalized):
        return []

    explicit = _extract_explicit(normalized)
    stable = _extract_stable_claims(normalized)
    candidates = explicit + stable

    # Use the model as a second-pass extractor when no deterministic rule fired.
    if not candidates:
        candidates = await _llm_extract_candidates(normalized)

    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        content = normalize_memory(candidate.get("content", ""))
        if not content or len(content) > 500:
            continue
        candidate["content"] = content
        candidate["memory_key"] = normalize_key(candidate.get("memory_key") or infer_memory_key(candidate.get("category", ""), content))
        candidate.setdefault("category", "preference")
        candidate.setdefault("source", "observed")
        candidate.setdefault("confidence", 0.7)
        candidate.setdefault("importance", 0.6)
        existing = deduped.get(candidate["memory_key"])
        if existing and existing.get("source") == "explicit" and candidate.get("source") != "explicit":
            continue
        deduped[candidate["memory_key"]] = candidate
    return list(deduped.values())[:5]


def _extract_explicit(text: str) -> list[dict[str, Any]]:
    candidates = []
    remember_match = re.search(r"(?:请)?记住[:：]?\s*(.+)", text)
    if remember_match:
        content = remember_match.group(1)
        category, key = classify_memory(content)
        candidates.append(_candidate(content, category, key, "explicit", 1.0, 0.9, "user asked to remember"))

    call_match = re.search(r"以后(?:请)?(?:都)?(?:叫我|称呼我)[:：]?\s*([^\s，。,.!！?？]{1,40})", text)
    if call_match:
        name = call_match.group(1)
        candidates.append(_candidate(f"用户希望被称呼为{name}", "identity", "identity.display_name", "explicit", 1.0, 0.95, "preferred name"))

    forget_match = re.search(r"(?:忘记|删除记忆|别再记住)[:：]?\s*(.+)", text)
    if forget_match:
        candidates.append(_candidate(forget_match.group(1), "forget_request", "control.forget", "explicit", 1.0, 1.0, "forget request"))
    return candidates


def _extract_stable_claims(text: str) -> list[dict[str, Any]]:
    candidates = []
    if _looks_like_question(text):
        return candidates
    name_match = re.search(r"(?:我是|我叫|本人是)\s*([^\s，。,.!！?？]{1,40})", text)
    if name_match:
        name = name_match.group(1)
        candidates.append(_candidate(f"用户姓名或自称是{name}", "identity", "identity.display_name", "observed", 0.9, 0.9, "self identification"))

    like_match = re.search(r"我(?:更)?(?:喜欢|偏好)\s*(.+)", text)
    if like_match:
        content = f"用户偏好：{like_match.group(1)}"
        candidates.append(_candidate(content, "preference", "preference.general", "observed", 0.75, 0.65, "stated preference"))

    dislike_match = re.search(r"我不喜欢\s*(.+)", text)
    if dislike_match:
        content = f"用户不喜欢：{dislike_match.group(1)}"
        candidates.append(_candidate(content, "preference", "preference.dislike", "observed", 0.75, 0.65, "stated dislike"))

    org_match = re.search(r"我的(?:公司|团队|部门|项目)(?:是|叫|为)\s*(.+)", text)
    if org_match:
        candidates.append(_candidate(f"用户组织信息：{org_match.group(1)}", "profile", "profile.organization", "observed", 0.8, 0.7, "organization profile"))
    return candidates


async def _llm_extract_candidates(text: str) -> list[dict[str, Any]]:
    try:
        from backend.graph import invoke_llm

        prompt = (
            "Extract durable user memories from the message. Return JSON only: "
            "{\"memories\":[{\"content\":\"...\",\"category\":\"identity|preference|profile|work_context|goal\","
            "\"memory_key\":\"stable dotted key\",\"confidence\":0.0,\"importance\":0.0,\"reason\":\"...\"}]}.\n"
            "Only include stable, future-useful information. Exclude secrets, health, financial, legal, one-off, or temporary details.\n"
            f"Message: {text}"
        )
        response = invoke_llm(prompt)
        raw = response.content.strip()
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return []
        payload = json.loads(match.group(0))
        memories = payload.get("memories", [])
        candidates = []
        for item in memories:
            if isinstance(item, dict):
                candidates.append(
                    _candidate(
                        item.get("content", ""),
                        item.get("category", "preference"),
                        item.get("memory_key", ""),
                        "observed",
                        float(item.get("confidence", 0.65)),
                        float(item.get("importance", 0.55)),
                        item.get("reason", "llm extracted"),
                    )
                )
        return candidates
    except Exception:
        return []


def classify_memory(content: str) -> tuple[str, str]:
    if re.search(r"(叫我|称呼我|我是|我叫|姓名|名字)", content):
        return "identity", "identity.display_name"
    if re.search(r"(公司|团队|部门|项目)", content):
        return "profile", "profile.organization"
    if re.search(r"(喜欢|偏好|不喜欢|习惯|格式|简洁|详细)", content):
        return "preference", "preference.general"
    return "preference", "preference.general"


def infer_memory_key(category: str, content: str) -> str:
    if category == "identity":
        return "identity.display_name"
    if category == "profile":
        return "profile.general"
    if category == "forget_request":
        return "control.forget"
    if "不喜欢" in content:
        return "preference.dislike"
    return f"{category or 'memory'}.general"


def normalize_key(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (value or "general").strip().lower())
    return value[:120] or "general"


def normalize_memory(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _candidate(
    content: str,
    category: str,
    memory_key: str,
    source: str,
    confidence: float,
    importance: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "content": normalize_memory(content),
        "category": category,
        "memory_key": normalize_key(memory_key),
        "source": source,
        "confidence": max(0.0, min(1.0, confidence)),
        "importance": max(0.0, min(1.0, importance)),
        "reason": reason,
    }


def _looks_ephemeral(text: str) -> bool:
    lowered = text.lower()
    terms = ("今天", "明天", "刚才", "现在", "这次", "临时", "today", "tomorrow", "right now")
    return any(term in lowered for term in terms)


def _looks_like_question(text: str) -> bool:
    lowered = text.lower().strip()
    question_markers = ("?", "？", "吗", "么", "谁", "什么", "如何", "怎么", "where", "what", "who", "how")
    return lowered.endswith(question_markers) or any(marker in lowered for marker in ("我是谁", "你知道我是谁"))


def _is_sensitive(text: str) -> bool:
    lowered = text.lower()
    terms = ("密码", "api key", "secret", "身份证", "银行卡", "token", "私钥")
    return any(term in lowered for term in terms)


async def _find_by_key(
    db: AsyncSession,
    user_id: int | None,
    scope_key: str,
    memory_key: str,
    *,
    status: str | None,
) -> UserMemory | None:
    stmt = select(UserMemory).where(UserMemory.scope_key == scope_key, UserMemory.memory_key == memory_key)
    stmt = stmt.where(UserMemory.user_id.is_(None) if user_id is None else UserMemory.user_id == user_id)
    if status:
        stmt = stmt.where(UserMemory.status == status)
    return await db.scalar(stmt.order_by(UserMemory.updated_at.desc()).limit(1))
