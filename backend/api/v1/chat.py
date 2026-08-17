"""
问答路由（向后兼容原有接口路径）
- POST /chat            — 普通问答（新增缓存 + 历史记录）
- POST /chat/stream     — SSE 流式问答
- POST /embeddings      — Embedding 测试
- POST /rerank          — Rerank 测试
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import List

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.api.deps import get_current_user, get_db_optional, get_redis_optional
from backend.core.config import settings
from backend.core.exceptions import AppError, ErrorCode
from backend.core.logging import get_logger
from backend.schemas.chat import ChatRequest, ChatResponse, EmbeddingRequest, RerankRequest
from backend.services.chat_service import run_chat

logger = get_logger(__name__)
router = APIRouter(tags=["问答"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
    redis=Depends(get_redis_optional),
):
    # 限流检查
    if redis is not None:
        from backend.services.cache_service import check_rate_limit
        client_ip = http_request.client.host if http_request.client else "unknown"
        if not await check_rate_limit(redis, client_ip):
            raise AppError(ErrorCode.RATE_LIMITED, "请求过于频繁，请稍后再试", 429)

    result = await run_chat(
        question=request.question,
        session_id=request.session_id,
        current_user=current_user,
        db=db,
        redis=redis,
    )
    return ChatResponse(**result)


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db_optional),
    redis=Depends(get_redis_optional),
):
    async def event_generator():
        from backend.graph import (
            MODEL_NAME, crag_app, has_valid_tavily_key, initial_state
        )
        seen_steps: set = set()
        final_state = None
        final_nodes = {"generate", "direct_answer"}
        start = time.perf_counter()

        yield _sse("meta", {"model": MODEL_NAME, "tavily_enabled": has_valid_tavily_key()})
        use_personal_context = db is not None and request.session_id is not None

        # Redis 缓存命中 → 直接推送
        if redis is not None and not use_personal_context:
            from backend.services.cache_service import get_cached_answer
            cached = await get_cached_answer(redis, request.question)
            if cached:
                cached["cached"] = True
                yield _sse("final", cached)
                return

        try:
            history_context = ""
            memory_context = ""
            if db is not None:
                from backend.services.chat_service import _format_history_context
                from backend.services.memory_service import format_memory_context
                if request.session_id is not None:
                    history_context = await _format_history_context(db, request.session_id)
                memory_context = await format_memory_context(db, current_user)

            stream = crag_app.stream(
                initial_state(request.question, history_context, memory_context),
                stream_mode=["updates", "messages"],
            )
            for mode, payload in stream:
                if mode == "updates":
                    for node, state in payload.items():
                        yield _sse("node", {"node": node})
                        for step in state.get("steps", []):
                            if step not in seen_steps:
                                seen_steps.add(step)
                                yield _sse("step", {"text": step})
                        if node in final_nodes:
                            final_state = state
                elif mode == "messages":
                    chunk, meta = payload
                    if meta.get("langgraph_node") not in final_nodes:
                        continue
                    token = getattr(chunk, "content", "")
                    if token:
                        yield _sse("token", {"text": token})
                        await asyncio.sleep(0)
                await asyncio.sleep(0)

            final_state = final_state or crag_app.invoke(initial_state(request.question, history_context, memory_context))
            response = {
                "answer": final_state.get("generation", ""),
                "agent_trace": final_state.get("steps", []),
                "trigger_web_fallback": bool(final_state.get("web_fallback", False)),
                "sources": final_state.get("sources", []),
                "reasoning_summary": final_state.get("reasoning_summary", []),
                "cached": False,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            }
            yield _sse("final", response)

            if db is not None and request.session_id is not None:
                from backend.services.chat_service import _save_history
                message_id = await _save_history(db, request.session_id, request.question, response, final_state)
            else:
                message_id = None
            if db is not None:
                from backend.services.memory_service import maybe_store_memories_from_turn
                await maybe_store_memories_from_turn(
                    db,
                    current_user,
                    request.question,
                    response["answer"],
                    session_id=request.session_id,
                    message_id=message_id,
                )

            # 写缓存
            if redis and response["answer"] and not use_personal_context:
                from backend.services.cache_service import set_cached_answer
                await set_cached_answer(redis, request.question, response)

        except Exception as exc:
            logger.error("chat_stream_error", error=str(exc), exc_info=exc)
            yield _sse("error", {"message": str(exc)})

    return EventSourceResponse(event_generator())


@router.post("/embeddings")
async def embeddings(request: EmbeddingRequest):
    from backend.retriever import knowledge_base
    texts = [request.input] if isinstance(request.input, str) else request.input
    vectors = knowledge_base.embedding.embed(texts)
    return {
        "object": "list",
        "model": request.model or knowledge_base.embedding.model_name,
        "data": [
            {"object": "embedding", "index": i, "embedding": v.tolist()}
            for i, v in enumerate(vectors)
        ],
    }


@router.post("/rerank")
async def rerank(request: RerankRequest):
    from backend.retriever import SearchResult, knowledge_base
    top_n = max(1, min(request.top_n, len(request.documents)))
    candidates = [
        SearchResult(content=doc, source=str(i), page=0, score=0.0, retrieval_score=0.0)
        for i, doc in enumerate(request.documents)
    ]
    if knowledge_base.reranker.enabled:
        ranked = knowledge_base.reranker.rerank(request.query, candidates, top_n)
        return {
            "model": request.model or knowledge_base.reranker.model_name,
            "results": [
                {"index": int(r.source), "relevance_score": r.score, "document": r.content}
                for r in ranked
            ],
        }
    vectors = knowledge_base.embedding.embed([request.query] + request.documents)
    scores = vectors[1:] @ vectors[0]
    order = scores.argsort()[::-1][:top_n]
    return {
        "model": "embedding-cosine-fallback",
        "results": [
            {"index": int(i), "relevance_score": round(float(scores[i]), 4), "document": request.documents[int(i)]}
            for i in order
        ],
    }


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
