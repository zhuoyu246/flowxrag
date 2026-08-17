from __future__ import annotations

from typing import Any, List, Literal, TypedDict
import os
import re
import time

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from backend.retriever import SearchResult, bm25_tokenize, knowledge_base
from backend.core.metrics import METRICS


Route = Literal["auto", "local", "web", "model"]


class GraphState(TypedDict):
    """State object passed between LangGraph nodes."""

    question: str
    history_context: str
    memory_context: str
    generation: str
    route: Route
    web_fallback: bool
    documents: List[dict]
    steps: List[str]
    sources: List[dict]
    reasoning_summary: List[str]


MODEL_NAME = os.getenv("OPENAI_MODEL", os.getenv("MODEL_NAME", "deepseek-chat"))
MODEL_BASE_URL = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4096"))
LOCAL_FIRST_MODE = os.getenv("LOCAL_FIRST_MODE", "true").strip().strip('"').strip("'").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# The large language model stays remote: DeepSeek API.
# Local CPU only handles document parsing, embeddings and FAISS retrieval.
llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=0,
    base_url=MODEL_BASE_URL,
    api_key=os.getenv("OPENAI_API_KEY"),
    max_tokens=OPENAI_MAX_TOKENS,
    timeout=60,
    max_retries=2,
    streaming=True,
)


def initial_state(question: str, history_context: str = "", memory_context: str = "") -> GraphState:
    return {
        "question": question,
        "history_context": history_context,
        "memory_context": memory_context,
        "generation": "",
        "route": "auto",
        "web_fallback": False,
        "documents": [],
        "steps": [],
        "sources": [],
        "reasoning_summary": [],
    }


def invoke_llm(prompt: str):
    """DeepSeek call helper with simple retry for temporary gateway errors."""
    last_error = None
    for attempt in range(3):
        started = time.perf_counter()
        try:
            response = llm.invoke(prompt)
            METRICS.llm_requests_total.labels(MODEL_NAME, "success").inc()
            return response
        except Exception as exc:
            last_error = exc
            METRICS.llm_requests_total.labels(MODEL_NAME, "error").inc()
            METRICS.llm_errors_total.labels(MODEL_NAME).inc()
            message = str(exc).lower()
            transient = any(code in message for code in ("502", "503", "504", "timeout", "temporarily"))
            if attempt < 2 and transient:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        finally:
            METRICS.rag_llm_duration_seconds.labels(MODEL_NAME).observe(time.perf_counter() - started)
    raise RuntimeError(f"DeepSeek call failed after retries: {last_error}")


def has_valid_tavily_key() -> bool:
    key = os.getenv("TAVILY_API_KEY", "").strip().strip('"').strip("'")
    return bool(key) and key.startswith("tvly-") and "your-tavily-api-key" not in key


def wants_web_search(question: str) -> bool:
    question = (question or "").lower()
    web_markers = (
        "天气",
        "气温",
        "下雨",
        "降雨",
        "台风",
        "空气质量",
        "股价",
        "股票",
        "汇率",
        "币价",
        "价格",
        "赛事",
        "赛程",
        "联网",
        "网上",
        "全网",
        "搜索一下",
        "查一下最新",
        "最新",
        "今天",
        "实时",
        "新闻",
        "当前",
        "现在",
        "web",
        "internet",
        "latest",
        "today",
        "current",
    )
    return any(marker in question for marker in web_markers)


def wants_document_search(question: str) -> bool:
    question = (question or "").lower()
    document_markers = (
        "文档",
        "文件",
        "pdf",
        "附件",
        "知识库",
        "已上传",
        "入库",
        "这篇",
        "这份",
        "这本",
        "这个材料",
        "这篇文章",
        "这篇论文",
        "论文",
        "报告",
        "研报",
        "简历",
        "合同",
        "标书",
        "材料",
        "材料里",
        "文档里",
        "文件里",
        "报告里",
        "简历里",
        "合同里",
        "依据",
        "页码",
        "章节",
        "作者",
        "讲什么",
        "写什么",
        "写的什么",
        "写得什么",
    )
    return any(marker in question for marker in document_markers)


def wants_direct_model(question: str) -> bool:
    question = (question or "").lower().strip()
    if not question:
        return True

    casual_patterns = (
        "你好",
        "hello",
        "hi",
        "你是谁",
        "你能做什么",
        "介绍一下你",
    )
    writing_markers = (
        "帮我写",
        "写一封",
        "润色",
        "翻译",
        "改写",
        "扩写",
        "起草",
        "生成一段",
        "写代码",
        "解释一下",
    )
    return any(marker in question for marker in casual_patterns + writing_markers)


def choose_route(question: str) -> Route:
    if wants_document_search(question):
        return "local"
    if wants_web_search(question):
        return "web"
    if wants_direct_model(question):
        return "model"
    return "auto"


def local_results_confident(question: str, documents: List[dict]) -> bool:
    if not documents:
        return False

    best_score = max(float(document["source_meta"].get("score") or 0) for document in documents)
    if best_score >= float(os.getenv("AUTO_LOCAL_SCORE_THRESHOLD", "0.55")):
        return True

    query_terms = {
        token
        for token in bm25_tokenize(question)
        if len(token) >= 2 and token not in {"这个", "那个", "什么", "怎么", "如何", "一下"}
    }
    if not query_terms:
        return False

    context = "\n".join(document["content"][:1200].lower() for document in documents[:3])
    overlap = sum(1 for token in query_terms if token in context)
    return overlap >= min(2, len(query_terms))


def search_web(query: str) -> tuple[str, List[dict]]:
    """Tavily web search. This is the web fallback retriever."""
    if not has_valid_tavily_key():
        raise RuntimeError("TAVILY_API_KEY is not configured.")

    tool = TavilySearchResults(
        max_results=5,
        search_depth="advanced",
        include_answer=True,
        include_raw_content=False,
    )
    return normalize_tavily_results(tool.invoke({"query": query}))


def normalize_tavily_results(results: Any) -> tuple[str, List[dict]]:
    if isinstance(results, str):
        return results, []

    if isinstance(results, dict):
        answer = results.get("answer", "")
        items = results.get("results", [results])
    else:
        answer = ""
        items = results or []

    text_blocks = [answer] if answer else []
    sources = []
    for item in items:
        if not isinstance(item, dict):
            text_blocks.append(str(item))
            continue

        title = item.get("title", "Web result")
        url = item.get("url", "")
        content = item.get("content") or item.get("raw_content") or ""
        text_blocks.append(f"- {title}\n  URL: {url}\n  Content: {content}".strip())
        sources.append({"source": title, "url": url, "type": "web", "score": item.get("score")})

    return "\n".join(text_blocks).strip(), sources


# -----------------------------
# LangGraph node 0: route
# -----------------------------
def route_question(state: GraphState):
    question = state["question"]
    route = choose_route(question)
    route_labels = {
        "local": "文档问答",
        "web": "联网搜索",
        "model": "直接回答",
        "auto": "自动判断",
    }
    state["steps"].append(f"自动选择：{route_labels[route]}")
    state["reasoning_summary"].append(f"系统根据问题意图选择“{route_labels[route]}”。")
    return {
        "question": question,
        "route": route,
        "documents": state["documents"],
        "sources": state["sources"],
        "steps": state["steps"],
        "reasoning_summary": state["reasoning_summary"],
    }


# -----------------------------
# LangGraph node 1: retrieve
# -----------------------------
def retrieve(state: GraphState):
    """Local RAG retrieval: question -> embedding -> FAISS top-k chunks."""
    question = state["question"]
    state["steps"].append("1. 本地检索：查询 FAISS 知识库")

    results = knowledge_base.search(question, top_k=5)
    documents = [search_result_to_document(result) for result in results]
    sources = [search_result_to_source(result) for result in results]

    if results:
        state["reasoning_summary"].append(f"本地知识库命中 {len(results)} 个候选片段。")
    else:
        state["reasoning_summary"].append("本地知识库没有命中候选片段。")

    return {
        "question": question,
        "route": state.get("route", "auto"),
        "documents": documents,
        "sources": sources,
        "steps": state["steps"],
        "reasoning_summary": state["reasoning_summary"],
    }


# -----------------------------
# LangGraph node 2: grade
# -----------------------------
def grade_documents(state: GraphState):
    """CRAG correction step: let DeepSeek judge whether retrieved chunks are useful."""
    question = state["question"]
    documents = state["documents"]
    state["steps"].append("2. 相关性评分：DeepSeek 判断本地片段是否能回答问题")

    route = state.get("route", "auto")

    if not documents:
        if route == "local":
            state["steps"].append("本地没有可用片段，返回缺少资料提示")
            state["reasoning_summary"].append("用户在问文档，但知识库没有命中可用内容。")
        else:
            state["steps"].append("本地没有高可信命中，交给模型直接回答")
            state["reasoning_summary"].append("没有找到可靠本地证据，使用通用模型回答。")
        return {
            "question": question,
            "route": "local" if route == "local" else "model",
            "documents": [],
            "web_fallback": False,
            "sources": state["sources"],
            "steps": state["steps"],
            "reasoning_summary": state["reasoning_summary"],
        }

    if route == "local":
        state["steps"].append("使用本地文档生成答案")
        state["reasoning_summary"].append("问题明确指向已入库文档，使用本地知识库。")
        return {
            "question": question,
            "route": "local",
            "documents": documents,
            "web_fallback": False,
            "sources": state["sources"],
            "steps": state["steps"],
            "reasoning_summary": state["reasoning_summary"],
        }

    if route == "auto" and local_results_confident(question, documents):
        state["steps"].append("自动判断为本地文档问题")
        state["reasoning_summary"].append("本地检索命中较可信，使用本地知识库回答。")
        return {
            "question": question,
            "route": "local",
            "documents": documents,
            "web_fallback": False,
            "sources": state["sources"],
            "steps": state["steps"],
            "reasoning_summary": state["reasoning_summary"],
        }

    if route == "auto":
        state["steps"].append("本地命中不够可信，交给模型直接回答")
        state["reasoning_summary"].append("未发现足够可靠的本地证据，避免硬套文档。")
        return {
            "question": question,
            "route": "model",
            "documents": [],
            "web_fallback": False,
            "sources": [],
            "steps": state["steps"],
            "reasoning_summary": state["reasoning_summary"],
        }

    grader_prompt = (
        "你是 RAG 相关性评分器。判断文档是否能直接回答问题。只输出 yes 或 no。\n\n"
        "文档：{document}\n"
        "问题：{question}"
    )

    kept_documents = []
    kept_sources = []
    for document in documents:
        score = invoke_llm(grader_prompt.format(document=document["content"], question=question))
        if score.content.strip().lower().startswith("yes"):
            kept_documents.append(document)
            kept_sources.append(document["source_meta"])

    web_fallback = len(kept_documents) == 0
    if web_fallback:
        kept_documents = documents
        kept_sources = state["sources"]
        web_fallback = False
        state["steps"].append("评分未保留片段，降级使用本地检索 Top-K，避免答非所问")
        state["reasoning_summary"].append("本地知识库已有候选片段，未切换到联网兜底。")
    else:
        state["steps"].append(f"保留 {len(kept_documents)} 个本地片段作为上下文")
        state["reasoning_summary"].append(f"本地检索结果通过评分，使用 {len(kept_documents)} 个片段生成答案。")

    return {
        "question": question,
        "route": "local",
        "documents": kept_documents,
        "web_fallback": web_fallback,
        "sources": kept_sources,
        "steps": state["steps"],
        "reasoning_summary": state["reasoning_summary"],
    }


# -----------------------------
# LangGraph node 3: web fallback
# -----------------------------
def web_search(state: GraphState):
    """If local RAG is weak, retrieve web evidence from Tavily."""
    question = state["question"]
    documents = state["documents"]
    sources = state["sources"]
    state["steps"].append("3. 联网兜底：Tavily 全网搜索")

    try:
        web_context, web_sources = search_web(question)
        documents.append(
            {
                "content": web_context,
                "source": "Tavily 全网搜索",
                "source_meta": {"source": "Tavily 全网搜索", "type": "web"},
            }
        )
        sources.extend(web_sources)
        state["steps"].append("Tavily 搜索完成")
        state["reasoning_summary"].append("使用 Tavily 获取联网资料，再交给 DeepSeek 综合。")
    except Exception as exc:
        state["steps"].append("Tavily 不可用，降级为 DeepSeek 常识兜底")
        fallback_prompt = (
            "联网搜索暂时不可用。请基于通用知识为下面问题整理背景材料；"
            "如果问题涉及实时信息，请说明可能不是最新。\n\n"
            f"问题：{question}"
        )
        response = invoke_llm(fallback_prompt)
        documents.append(
            {
                "content": response.content,
                "source": "DeepSeek 模型知识兜底",
                "source_meta": {"source": "DeepSeek 模型知识兜底", "type": "model"},
            }
        )
        sources.append({"source": "DeepSeek 模型知识兜底", "type": "model"})
        state["reasoning_summary"].append(f"Tavily 调用失败，已降级为模型知识兜底：{exc}")

    return {
        "question": question,
        "route": "web",
        "documents": documents,
        "web_fallback": True,
        "sources": sources,
        "steps": state["steps"],
        "reasoning_summary": state["reasoning_summary"],
    }


# -----------------------------
# LangGraph node 4a: direct model answer
# -----------------------------
def direct_answer(state: GraphState):
    question = state["question"]
    personalization = _personalization_block(
        state.get("history_context", ""),
        state.get("memory_context", ""),
    )
    state["steps"].append("直接回答：使用通用模型能力")
    prompt = (
        "你是一个自然、可靠的中文助手。请直接回答用户问题。\n"
        "如果问题明显需要实时信息，但没有联网搜索结果，请提醒用户需要联网查询。\n"
        "回答要像 ChatGPT 一样自然，不要提及内部路由、工具链或调试过程。\n\n"
        f"{personalization}"
        f"问题：{question}"
    )
    response = invoke_llm(prompt)
    state["steps"].append("任务完成")
    return {
        "question": question,
        "route": "model",
        "generation": response.content,
        "web_fallback": False,
        "documents": [],
        "sources": [],
        "steps": state["steps"],
        "reasoning_summary": state["reasoning_summary"],
    }


# -----------------------------
# LangGraph node 4b: generate with evidence
# -----------------------------
def generate(state: GraphState):
    """Final generation: DeepSeek answers with retrieved context."""
    question = state["question"]
    documents = state["documents"]
    personalization = _personalization_block(
        state.get("history_context", ""),
        state.get("memory_context", ""),
    )
    state["steps"].append("4. 答案生成：DeepSeek 基于检索上下文回答")

    context = "\n\n".join(
        f"[{index + 1}] {document['source']}\n{document['content']}"
        for index, document in enumerate(documents)
    )
    reasoning_summary = "\n".join(f"- {item}" for item in state["reasoning_summary"])

    prompt = (
        "你是一个自然、可靠的中文助手。请基于上下文回答用户问题。\n"
        "要求：\n"
        "1. 先给直接答案，再给关键依据。\n"
        "2. 不要输出隐藏思维链，也不要提及内部路由、工具链或调试过程。\n"
        "3. 优先使用本地知识库；只有上下文里出现 Tavily 资料时，才说明来自联网检索。\n"
        "4. 中文回答，结构清晰。\n"
        "5. 除非用户明确要求“简短/一句话”，否则不要过短；请充分展开，至少包含：直接结论、关键依据、分点分析、可执行建议或注意事项。\n"
        "6. 如果用户问“这篇/这份文档讲什么、总结一下、主要内容”，请直接对本地文档做概览总结，不要回答成缺少论文内容。\n"
        "7. 如果上下文证据充足，回答应尽量完整；如果证据不足，要明确说明缺口，并给出下一步检索或补充材料建议。\n\n"
        f"推理摘要：\n{reasoning_summary}\n\n"
        f"{personalization}"
        f"上下文：\n{context}\n\n"
        f"问题：{question}"
    )
    response = invoke_llm(prompt)

    state["steps"].append("任务完成")
    return {
        "question": question,
        "route": state.get("route", "local"),
        "generation": response.content,
        "web_fallback": state.get("web_fallback", False),
        "documents": documents,
        "sources": state["sources"],
        "steps": state["steps"],
        "reasoning_summary": state["reasoning_summary"],
    }


def search_result_to_document(result: SearchResult) -> dict:
    source_meta = search_result_to_source(result)
    return {
        "content": result.content,
        "source": f"{result.source} p.{result.page}",
        "source_meta": source_meta,
    }


def search_result_to_source(result: SearchResult) -> dict:
    return {
        "source": result.source,
        "page": result.page,
        "score": result.score,
        "retrieval_score": result.retrieval_score,
        "type": "local",
    }


def _personalization_block(history_context: str, memory_context: str) -> str:
    blocks = []
    if memory_context:
        blocks.append(
            "长期记忆（只用于个性化、偏好和称呼；不要把它当作事实证据）：\n"
            f"{memory_context}"
        )
    if history_context:
        blocks.append(
            "最近会话（用于理解代词、省略和延续问题）：\n"
            f"{history_context}"
        )
    if not blocks:
        return ""
    priority = (
        "记忆使用规则：当前用户消息优先级最高；如果当前消息与长期记忆冲突，"
        "以当前消息为准，并自然承认更新，不要被旧记忆误导。\n"
    )
    return priority + "\n\n".join(blocks) + "\n\n"


def decide_after_route(state: GraphState):
    route = state.get("route", "auto")
    if route == "web":
        return "web_search"
    if route == "model":
        return "direct_answer"
    return "retrieve"


def decide_to_generate(state: GraphState):
    if state.get("route") == "model":
        return "direct_answer"
    return "web_search" if state.get("web_fallback") else "generate"


# This is the complete CRAG graph:
# retrieve -> grade_documents -> (web_search if weak) -> generate
workflow = StateGraph(GraphState)
workflow.add_node("route_question", route_question)
workflow.add_node("retrieve", retrieve)
workflow.add_node("grade_documents", grade_documents)
workflow.add_node("web_search", web_search)
workflow.add_node("direct_answer", direct_answer)
workflow.add_node("generate", generate)

workflow.set_entry_point("route_question")
workflow.add_conditional_edges(
    "route_question",
    decide_after_route,
    {"retrieve": "retrieve", "web_search": "web_search", "direct_answer": "direct_answer"},
)
workflow.add_edge("retrieve", "grade_documents")
workflow.add_conditional_edges(
    "grade_documents",
    decide_to_generate,
    {"web_search": "web_search", "generate": "generate", "direct_answer": "direct_answer"},
)
workflow.add_edge("web_search", "generate")
workflow.add_edge("direct_answer", END)
workflow.add_edge("generate", END)

crag_app = workflow.compile()
