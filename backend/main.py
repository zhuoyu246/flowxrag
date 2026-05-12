from __future__ import annotations

from typing import List
import asyncio
import json
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

load_dotenv(override=True)


def _clean_env(name: str) -> str:
    return os.getenv(name, "").strip().strip('"').strip("'")


def _valid_secret(value: str) -> bool:
    lowered = value.lower()
    return bool(value) and "your-" not in lowered and "placeholder" not in lowered


def configure_langsmith() -> dict:
    langchain_key = _clean_env("LANGCHAIN_API_KEY")
    langsmith_key = _clean_env("LANGSMITH_API_KEY")
    api_key = langchain_key if _valid_secret(langchain_key) else langsmith_key

    if _valid_secret(api_key):
        os.environ["LANGCHAIN_API_KEY"] = api_key
        os.environ.setdefault("LANGCHAIN_PROJECT", "crag-expert-system")
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_TRACING"] = "true"
        return {
            "enabled": True,
            "project": os.getenv("LANGCHAIN_PROJECT", "crag-expert-system"),
            "endpoint": os.getenv("LANGCHAIN_ENDPOINT") or os.getenv("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com",
        }

    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    return {
        "enabled": False,
        "project": os.getenv("LANGCHAIN_PROJECT", "crag-expert-system"),
        "endpoint": os.getenv("LANGCHAIN_ENDPOINT") or os.getenv("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com",
        "reason": "LANGCHAIN_API_KEY or LANGSMITH_API_KEY is empty/placeholder.",
    }


LANGSMITH_STATUS = configure_langsmith()

from backend.graph import (  # noqa: E402
    MODEL_BASE_URL,
    MODEL_NAME,
    OPENAI_MAX_TOKENS,
    crag_app,
    has_valid_tavily_key,
    initial_state,
    invoke_llm,
    search_web,
)
from backend.retriever import SearchResult, knowledge_base  # noqa: E402


app = FastAPI(title="CRAG Expert System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    agent_trace: List[str]
    trigger_web_fallback: bool
    sources: List[dict] = []
    reasoning_summary: List[str] = []


class EmbeddingRequest(BaseModel):
    input: str | List[str]
    model: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    top_n: int = 5
    model: str | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "base_url": MODEL_BASE_URL,
        "max_tokens": OPENAI_MAX_TOKENS,
        "tavily_enabled": has_valid_tavily_key(),
        "langsmith": LANGSMITH_STATUS,
        "knowledge_base": knowledge_base.stats(),
    }


@app.get("/model-health")
def model_health():
    response = invoke_llm("请只回复 OK。")
    return {
        "status": "ok",
        "provider": "deepseek",
        "model": MODEL_NAME,
        "base_url": MODEL_BASE_URL,
        "sample": response.content,
    }


@app.get("/search-health")
def search_health():
    result, sources = search_web("Tavily API test")
    return {
        "status": "ok",
        "provider": "tavily",
        "enabled": True,
        "sample": result[:500],
        "sources": sources[:3],
    }


@app.get("/embedding-health")
def embedding_health():
    vectors = knowledge_base.embedding.embed(["embedding api health check"])
    return {
        "status": "ok",
        **knowledge_base.embedding.stats(),
        "sample_dimension": int(vectors.shape[1]) if len(vectors) else 0,
    }


@app.get("/rerank-health")
def rerank_health():
    sample = knowledge_base.reranker.rerank(
        "企业知识库检索",
        [
            SearchResult(content="企业知识库需要先检索再生成。", source="sample-0", page=0, score=0.0),
            SearchResult(content="今天天气不错。", source="sample-1", page=0, score=0.0),
        ],
        top_k=2,
    )
    return {
        "status": "ok",
        **knowledge_base.reranker.stats(),
        "sample": [result.__dict__ for result in sample],
    }


@app.post("/embeddings")
def embeddings(request: EmbeddingRequest):
    texts = [request.input] if isinstance(request.input, str) else request.input
    vectors = knowledge_base.embedding.embed(texts)
    return {
        "object": "list",
        "model": request.model or knowledge_base.embedding.model_name,
        "data": [
            {
                "object": "embedding",
                "index": index,
                "embedding": vector.tolist(),
            }
            for index, vector in enumerate(vectors)
        ],
    }


@app.post("/rerank")
def rerank(request: RerankRequest):
    top_n = max(1, min(request.top_n, len(request.documents)))
    candidates = [
        SearchResult(content=document, source=str(index), page=0, score=0.0, retrieval_score=0.0)
        for index, document in enumerate(request.documents)
    ]

    if knowledge_base.reranker.enabled:
        ranked = knowledge_base.reranker.rerank(request.query, candidates, top_n)
        return {
            "model": request.model or knowledge_base.reranker.model_name,
            "results": [
                {
                    "index": int(result.source),
                    "relevance_score": result.score,
                    "document": result.content,
                }
                for result in ranked
            ],
        }

    vectors = knowledge_base.embedding.embed([request.query] + request.documents)
    query_vector = vectors[0]
    doc_vectors = vectors[1:]
    scores = doc_vectors @ query_vector
    order = scores.argsort()[::-1][:top_n]
    return {
        "model": request.model or "embedding-cosine-fallback",
        "results": [
            {
                "index": int(index),
                "relevance_score": round(float(scores[index]), 4),
                "document": request.documents[int(index)],
            }
            for index in order
        ],
    }


@app.get("/documents")
def documents():
    return knowledge_base.stats()


@app.post("/documents/upload")
def upload_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        return {"status": "error", "message": "Only PDF files are supported."}
    saved_path = knowledge_base.save_upload(file)
    result = knowledge_base.add_pdf(saved_path, file.filename)
    return {"status": "ok", **result}


@app.delete("/documents")
def clear_documents():
    knowledge_base.clear()
    return {"status": "ok", **knowledge_base.stats()}


@app.delete("/documents/source")
def delete_document(source: str = Query(..., min_length=1)):
    result = knowledge_base.delete_source(source)
    status = "ok" if result["chunks_removed"] or result["uploads_deleted"] else "not_found"
    return {"status": status, **result}


@app.post("/documents/reindex")
def reindex_documents():
    return {"status": "ok", **knowledge_base.rebuild_from_uploads()}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        result = crag_app.invoke(initial_state(request.question))
    except Exception as exc:
        return {
            "answer": f"后端处理失败：{exc}",
            "agent_trace": ["后端异常，已返回可读错误。请检查 DeepSeek/Tavily API Key、余额或网络代理。"],
            "trigger_web_fallback": False,
            "sources": [],
            "reasoning_summary": [],
        }

    return {
        "answer": result.get("generation", ""),
        "agent_trace": result.get("steps", []),
        "trigger_web_fallback": bool(result.get("web_fallback", False)),
        "sources": result.get("sources", []),
        "reasoning_summary": result.get("reasoning_summary", []),
    }


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def event_generator():
        seen_steps = set()
        final_state = None
        yield sse("meta", {"model": MODEL_NAME, "tavily_enabled": has_valid_tavily_key()})

        try:
            stream = crag_app.stream(
                initial_state(request.question),
                stream_mode=["updates", "messages"],
            )
            for mode, payload in stream:
                if mode == "updates":
                    for node, state in payload.items():
                        yield sse("node", {"node": node})
                        for step in state.get("steps", []):
                            if step not in seen_steps:
                                seen_steps.add(step)
                                yield sse("step", {"text": step})
                        if node == "generate":
                            final_state = state

                elif mode == "messages":
                    message_chunk, metadata = payload
                    if metadata.get("langgraph_node") != "generate":
                        continue
                    token = getattr(message_chunk, "content", "")
                    if token:
                        for char in token:
                            yield sse("token", {"text": char})
                            await asyncio.sleep(0)

                await asyncio.sleep(0)

            final_state = final_state or crag_app.invoke(initial_state(request.question))
            answer = final_state.get("generation", "")
            yield sse(
                "final",
                {
                    "answer": answer,
                    "agent_trace": final_state.get("steps", []),
                    "trigger_web_fallback": bool(final_state.get("web_fallback", False)),
                    "sources": final_state.get("sources", []),
                    "reasoning_summary": final_state.get("reasoning_summary", []),
                },
            )
        except Exception as exc:
            yield sse("error", {"message": str(exc)})

    return EventSourceResponse(event_generator())


def sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
