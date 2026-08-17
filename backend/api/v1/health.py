"""
健康检查路由
- GET /health           — 综合健康状态（DB + Redis + 模型 + 知识库）
- GET /model-health     — LLM 连通性测试
- GET /search-health    — Tavily 连通性测试
- GET /embedding-health — Embedding 服务测试
- GET /rerank-health    — Rerank 服务测试
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["健康检查"])


@router.get("/health")
async def health():
    from backend.db.database import init_db
    from backend.db.redis_client import ping_redis
    from backend.core.config import settings
    from backend.graph import MODEL_NAME, MODEL_BASE_URL, OPENAI_MAX_TOKENS, has_valid_tavily_key
    from backend.retriever import knowledge_base

    redis_ok = await ping_redis()

    return {
        "status": "ok",
        "app_version": settings.app_version,
        "app_env": settings.app_env,
        "model": MODEL_NAME,
        "base_url": MODEL_BASE_URL,
        "max_tokens": OPENAI_MAX_TOKENS,
        "tavily_enabled": has_valid_tavily_key(),
        "database": {"enabled": settings.db_enabled},
        "redis": {"enabled": settings.redis_enabled, "connected": redis_ok},
        "cache_enabled": settings.cache_enabled,
        "require_auth": settings.require_auth,
        "knowledge_base": knowledge_base.stats(),
    }


@router.get("/model-health")
def model_health():
    from backend.graph import MODEL_NAME, MODEL_BASE_URL, invoke_llm
    response = invoke_llm("请只回复 OK。")
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "base_url": MODEL_BASE_URL,
        "sample": response.content,
    }


@router.get("/search-health")
def search_health():
    from backend.graph import search_web
    result, sources = search_web("Tavily API test")
    return {"status": "ok", "provider": "tavily", "sample": result[:500], "sources": sources[:3]}


@router.get("/embedding-health")
def embedding_health():
    from backend.retriever import knowledge_base
    vectors = knowledge_base.embedding.embed(["embedding health check"])
    return {
        "status": "ok",
        **knowledge_base.embedding.stats(),
        "sample_dimension": int(vectors.shape[1]) if len(vectors) else 0,
    }


@router.get("/rerank-health")
def rerank_health():
    from backend.retriever import SearchResult, knowledge_base
    sample = knowledge_base.reranker.rerank(
        "企业知识库检索",
        [
            SearchResult(content="企业知识库需要先检索再生成。", source="s0", page=0, score=0.0),
            SearchResult(content="今天天气不错。", source="s1", page=0, score=0.0),
        ],
        top_k=2,
    )
    return {"status": "ok", **knowledge_base.reranker.stats(), "sample": [r.__dict__ for r in sample]}
