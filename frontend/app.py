import json
import os

import requests
import streamlit as st


BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
APP_VERSION = "nexusrag-console-20260511"


def api_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def stream_chat(question: str):
    response = api_session().post(
        f"{BACKEND_URL}/chat/stream",
        json={"question": question},
        stream=True,
        timeout=240,
    )
    response.raise_for_status()

    event = "message"
    data_lines = []
    for raw_line in response.iter_lines(decode_unicode=True):
        line = (raw_line or "").strip("\r")
        if not line:
            if data_lines:
                yield event, json.loads("\n".join(data_lines))
            event = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())


def upload_pdf(file) -> dict:
    files = {"file": (file.name, file.getvalue(), "application/pdf")}
    response = api_session().post(f"{BACKEND_URL}/documents/upload", files=files, timeout=180)
    response.raise_for_status()
    return response.json()


def get_json(path: str) -> dict:
    response = api_session().get(f"{BACKEND_URL}{path}", timeout=20)
    response.raise_for_status()
    return response.json()


def delete_document(source: str) -> dict:
    response = api_session().delete(
        f"{BACKEND_URL}/documents/source",
        params={"source": source},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def render_css() -> None:
    st.markdown(
        """
<style>
    .block-container {
        max-width: 1180px;
        padding-top: 2.1rem;
        padding-bottom: 7rem;
    }
    [data-testid="stSidebar"] {
        background: #f5f7fb;
        border-right: 1px solid #e4e8f0;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #182235;
    }
    .nexus-header {
        border: 1px solid #dfe6f1;
        border-radius: 8px;
        padding: 22px 24px;
        background: #ffffff;
        margin-bottom: 18px;
    }
    .nexus-title {
        font-size: 34px;
        font-weight: 760;
        color: #101827;
        line-height: 1.12;
        margin: 0 0 8px 0;
        letter-spacing: 0;
    }
    .nexus-subtitle {
        font-size: 15px;
        color: #5f6b7a;
        margin: 0;
    }
    .status-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 16px;
    }
    .status-pill {
        display: inline-flex;
        align-items: center;
        border: 1px solid #d9e2ef;
        border-radius: 6px;
        padding: 5px 9px;
        color: #314157;
        background: #f8fafc;
        font-size: 13px;
        white-space: nowrap;
    }
    .pipeline {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin: 12px 0 20px 0;
    }
    .pipeline-card {
        border: 1px solid #dfe6f1;
        border-radius: 8px;
        background: #ffffff;
        padding: 14px 14px 12px 14px;
        min-height: 118px;
    }
    .pipeline-step {
        font-size: 12px;
        color: #64748b;
        margin-bottom: 8px;
    }
    .pipeline-title {
        font-size: 16px;
        font-weight: 700;
        color: #172033;
        margin-bottom: 7px;
    }
    .pipeline-desc {
        color: #5f6b7a;
        font-size: 13px;
        line-height: 1.55;
    }
    .doc-card {
        border: 1px solid #dfe6f1;
        border-radius: 8px;
        padding: 12px;
        background: #ffffff;
        margin-bottom: 12px;
    }
    .doc-name {
        color: #182235;
        font-weight: 700;
        line-height: 1.35;
        word-break: break-word;
        margin-bottom: 6px;
    }
    .doc-meta {
        color: #6b7280;
        font-size: 12px;
    }
    .small-note {
        color: #667085;
        font-size: 13px;
        line-height: 1.55;
    }
    div[data-testid="stChatInput"] {
        max-width: 1180px;
        margin: 0 auto;
    }
    .stButton > button {
        border-radius: 7px;
    }
    @media (max-width: 900px) {
        .pipeline {
            grid-template-columns: 1fr;
        }
        .nexus-title {
            font-size: 27px;
        }
    }
</style>
        """,
        unsafe_allow_html=True,
    )


def render_header(health: dict, docs: dict) -> None:
    model = health.get("model", "-")
    online = "联网可用" if health.get("tavily_enabled") else "联网未配置"
    tracing = "LangSmith 已启用" if health.get("langsmith", {}).get("enabled") else "LangSmith 未启用"
    source_count = docs.get("source_count", 0)
    chunks = docs.get("chunks", 0)
    retrieval = docs.get("retrieval_mode", "-")

    st.markdown(
        f"""
<section class="nexus-header">
    <div class="nexus-title">NexusRAG 智能知识中枢</div>
    <p class="nexus-subtitle">面向本地文档、实时检索和通用问答的统一知识入口。</p>
    <div class="status-row">
        <span class="status-pill">模型 {model}</span>
        <span class="status-pill">{online}</span>
        <span class="status-pill">{tracing}</span>
        <span class="status-pill">文档 {source_count}</span>
        <span class="status-pill">片段 {chunks}</span>
        <span class="status-pill">{retrieval}</span>
    </div>
</section>
        """,
        unsafe_allow_html=True,
    )


def render_pipeline() -> None:
    st.markdown(
        """
<section class="pipeline">
    <div class="pipeline-card">
        <div class="pipeline-step">01</div>
        <div class="pipeline-title">意图路由</div>
        <div class="pipeline-desc">自动判断文档问答、实时检索或直接模型回答，用户不需要指定工具。</div>
    </div>
    <div class="pipeline-card">
        <div class="pipeline-step">02</div>
        <div class="pipeline-title">混合召回</div>
        <div class="pipeline-desc">向量检索与 BM25 关键词检索并行，使用 RRF 融合排序。</div>
    </div>
    <div class="pipeline-card">
        <div class="pipeline-step">03</div>
        <div class="pipeline-title">上下文治理</div>
        <div class="pipeline-desc">子块精准命中，父块补足上下文，再由重排模型优化证据顺序。</div>
    </div>
    <div class="pipeline-card">
        <div class="pipeline-step">04</div>
        <div class="pipeline-title">生成与观测</div>
        <div class="pipeline-desc">DeepSeek 流式生成，LangSmith 记录调用链、耗时和错误。</div>
    </div>
</section>
        """,
        unsafe_allow_html=True,
    )


def render_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander("参考来源", expanded=False):
        for source in sources:
            title = source.get("source") or source.get("url") or "来源"
            url = source.get("url")
            if url:
                st.markdown(f"- [{title}]({url})")
            else:
                meta = f" p.{source.get('page')}" if source.get("page") else ""
                st.markdown(f"- {title}{meta}")


def render_process(agent_trace: list[str]) -> None:
    if not agent_trace:
        return
    with st.expander("处理过程", expanded=False):
        for step in agent_trace:
            st.markdown(f"- {step}")


def render_document_card(document: dict, index: int) -> None:
    source = document.get("source", "")
    parent_chunks = document.get("parent_chunks", 0)
    chunks = document.get("chunks", 0)
    upload_count = document.get("upload_count", 0)
    confirm_key = f"confirm_delete_{index}_{source}"

    st.markdown(
        f"""
<div class="doc-card">
    <div class="doc-name">{source}</div>
    <div class="doc-meta">父块 {parent_chunks} · 子块 {chunks} · 文件 {upload_count}</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    st.checkbox("确认删除", key=confirm_key)
    if st.button(
        "删除文档",
        key=f"delete_document_{index}_{source}",
        disabled=not st.session_state.get(confirm_key, False),
        use_container_width=True,
    ):
        with st.spinner("正在删除文档并重建索引..."):
            result = delete_document(source)
        if result.get("status") == "ok":
            st.success(f"已删除：{source}")
        else:
            st.warning(f"没有找到可删除的文档：{source}")
        st.rerun()


st.set_page_config(page_title="NexusRAG 智能知识中枢", layout="wide", page_icon="N")
render_css()

if st.session_state.get("_app_version") != APP_VERSION:
    st.session_state.clear()
    st.session_state["_app_version"] = APP_VERSION

if "messages" not in st.session_state:
    st.session_state.messages = []


health = {}
docs = {}
try:
    health = get_json("/health")
    docs = get_json("/documents")
except Exception as exc:
    st.warning(f"后端未连接：{exc}")


with st.sidebar:
    st.header("文档控制台")
    uploaded = st.file_uploader("上传 PDF", type="pdf")
    if uploaded and st.button("入库并索引", use_container_width=True):
        with st.spinner("正在解析文档、切分父子块并重建索引..."):
            upload_pdf(uploaded)
        st.success("入库完成")
        st.rerun()

    st.markdown("---")
    st.subheader("已入库文档")
    documents = docs.get("documents", [])
    if documents:
        for index, document in enumerate(documents):
            render_document_card(document, index)
    else:
        st.caption("暂无已入库文档")

    st.markdown("---")
    with st.expander("运行状态", expanded=False):
        st.write(f"模型：`{health.get('model', '-')}`")
        st.write(f"联网：`{'已启用' if health.get('tavily_enabled') else '未启用'}`")
        st.write(f"LangSmith：`{'已启用' if health.get('langsmith', {}).get('enabled') else '未启用'}`")
        st.write(f"检索模式：`{docs.get('retrieval_mode', '-')}`")
        st.write(f"索引片段：`{docs.get('chunks', 0)}`")
        st.write(f"父块数量：`{docs.get('parent_chunks', 0)}`")


render_header(health, docs)
render_pipeline()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        render_sources(message.get("sources", []))
        render_process(message.get("agent_trace", []))


user_query = st.chat_input("输入问题，系统会自动选择文档检索、联网检索或直接回答")

if user_query:
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.chat_message("assistant"):
        answer_box = st.empty()
        answer = ""
        traces = []
        sources = []

        try:
            for event, payload in stream_chat(user_query):
                if event == "step":
                    traces.append(payload.get("text", ""))
                elif event == "token":
                    answer += payload.get("text", "")
                    answer_box.markdown(answer + "▌")
                elif event == "final":
                    answer = payload.get("answer", answer)
                    traces = payload.get("agent_trace", traces)
                    sources = payload.get("sources", [])
                    answer_box.markdown(answer)
                elif event == "error":
                    raise RuntimeError(payload.get("message", "stream error"))

            render_sources(sources)
            render_process(traces)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "sources": sources,
                    "agent_trace": traces,
                }
            )

        except Exception as exc:
            st.error(f"服务请求失败：{exc}")
