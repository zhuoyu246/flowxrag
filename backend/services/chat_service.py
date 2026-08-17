"""Chat orchestration service with cache, history and memory integration."""
from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger

logger = get_logger(__name__)


async def run_chat(
    question: str,
    session_id: int | None = None,
    current_user=None,
    db: AsyncSession | None = None,
    redis=None,
) -> dict:
    """Run the CRAG graph and persist optional history and memory."""
    use_personal_context = db is not None and session_id is not None
    if redis is not None and not use_personal_context:
        from backend.services.cache_service import get_cached_answer

        cached = await get_cached_answer(redis, question)
        if cached:
            cached["cached"] = True
            cached["duration_ms"] = 0
            logger.info("chat_cache_hit", question_preview=question[:50])
            return cached

    start = time.perf_counter()
    try:
        from backend.graph import crag_app, initial_state

        history_context = await _format_history_context(db, session_id) if db is not None and session_id else ""
        memory_context = ""
        if db is not None:
            from backend.services.memory_service import format_memory_context

            memory_context = await format_memory_context(db, current_user)
        result = crag_app.invoke(initial_state(question, history_context, memory_context))
    except Exception as exc:
        logger.error("crag_invoke_error", error=str(exc), exc_info=exc)
        return {
            "answer": f"后端处理失败：{exc}",
            "agent_trace": ["后端异常，请检查 API Key、余额或网络代理。"],
            "trigger_web_fallback": False,
            "sources": [],
            "reasoning_summary": [],
            "cached": False,
            "duration_ms": 0,
        }

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "chat_completed",
        question_preview=question[:50],
        route=result.get("route"),
        web_fallback=result.get("web_fallback"),
        duration_ms=duration_ms,
    )

    response = {
        "answer": result.get("generation", ""),
        "agent_trace": result.get("steps", []),
        "trigger_web_fallback": bool(result.get("web_fallback", False)),
        "sources": result.get("sources", []),
        "reasoning_summary": result.get("reasoning_summary", []),
        "cached": False,
        "duration_ms": duration_ms,
    }

    if redis is not None and response["answer"] and not use_personal_context:
        from backend.services.cache_service import set_cached_answer

        await set_cached_answer(redis, question, response)

    message_id = None
    if db is not None and session_id is not None:
        message_id = await _save_history(db, session_id, question, response, result)
    if db is not None:
        from backend.services.memory_service import maybe_store_memories_from_turn

        await maybe_store_memories_from_turn(
            db,
            current_user,
            question,
            response["answer"],
            session_id=session_id,
            message_id=message_id,
        )

    return response


async def _format_history_context(db: AsyncSession, session_id: int, limit: int = 8) -> str:
    """Return compact recent chat history for follow-up questions."""
    try:
        from sqlalchemy import select
        from backend.models.chat_history import ChatHistory

        result = await db.execute(
            select(ChatHistory)
            .where(ChatHistory.session_id == session_id)
            .order_by(ChatHistory.created_at.desc())
            .limit(limit)
        )
        rows = list(reversed(result.scalars().all()))
        lines = []
        for item in rows:
            lines.append(f"用户：{(item.question or '')[:300]}\n助手：{(item.answer or '')[:600]}")
        return "\n\n".join(lines)
    except Exception as exc:
        logger.warning("chat_history_context_failed", error=str(exc))
        return ""


async def _save_history(db: AsyncSession, session_id: int, question: str, response: dict, result: dict) -> int | None:
    """Persist a chat turn and return the created history id."""
    try:
        from sqlalchemy import update
        from backend.models.chat_history import ChatHistory
        from backend.models.session import ChatSession

        history = ChatHistory(
            session_id=session_id,
            question=question,
            answer=response["answer"],
            route=result.get("route"),
            sources=response["sources"],
            agent_trace=response["agent_trace"],
            duration_ms=response["duration_ms"],
            web_fallback=response["trigger_web_fallback"],
            cached=response["cached"],
        )
        db.add(history)
        await db.flush()

        await db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(message_count=ChatSession.message_count + 1)
        )
        await db.flush()
        logger.debug("chat_history_saved", session_id=session_id)
        return history.id
    except Exception as exc:
        logger.warning("chat_history_save_failed", error=str(exc))
        return None
