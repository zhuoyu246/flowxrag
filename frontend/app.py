from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import requests
import streamlit as st


BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
APP_VERSION = "nexusrag-workspace-20260526"


# ----------------------------- API client -----------------------------
def api_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    token = st.session_state.get("access_token")
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
    return session


def request_json(method: str, path: str, **kwargs) -> Any:
    response = api_session().request(
        method,
        f"{BACKEND_URL}{path}",
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )
    if response.status_code == 204:
        return {"ok": True}
    try:
        payload = response.json()
    except Exception:
        payload = {"message": response.text}
    if response.status_code >= 400:
        message = payload.get("message") or payload.get("detail") or response.text
        raise RuntimeError(f"{response.status_code}: {message}")
    return payload


def get_json(path: str) -> Any:
    return request_json("GET", path)


def post_json(path: str, payload: dict | None = None) -> Any:
    return request_json("POST", path, json=payload or {})


def delete_json(path: str) -> Any:
    return request_json("DELETE", path)


def upload_pdf(file, *, async_mode: bool = False) -> dict:
    path = "/api/v1/documents/upload/async" if async_mode else "/documents/upload"
    files = {"file": (file.name, file.getvalue(), "application/pdf")}
    response = api_session().post(f"{BACKEND_URL}{path}", files=files, timeout=300)
    if response.status_code >= 400:
        try:
            payload = response.json()
            message = payload.get("message") or payload.get("detail") or payload
        except Exception:
            message = response.text
        raise RuntimeError(f"{response.status_code}: {message}")
    return response.json()


def stream_chat(question: str, session_id: int | None = None):
    payload = {"question": question, "session_id": session_id}
    response = api_session().post(
        f"{BACKEND_URL}/chat/stream",
        json=payload,
        stream=True,
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text)

    event = "message"
    data_lines: list[str] = []
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


# ----------------------------- Session state -----------------------------
def init_state() -> None:
    if st.session_state.get("_app_version") != APP_VERSION:
        st.session_state.clear()
        st.session_state["_app_version"] = APP_VERSION
    defaults = {
        "messages": [],
        "active_view": "chat",
        "chat_session_id": None,
        "last_trace": [],
        "last_sources": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def login(email: str, password: str) -> None:
    token = post_json("/api/v1/auth/login", {"email": email, "password": password})
    st.session_state.access_token = token["access_token"]
    st.session_state.token_expires_in = token.get("expires_in", 0)
    st.session_state.current_user = get_json("/api/v1/auth/me")
    st.session_state.messages = []
    st.session_state.chat_session_id = None
    ensure_chat_session()


def register(email: str, username: str, password: str) -> None:
    post_json("/api/v1/auth/register", {"email": email, "username": username, "password": password})
    login(email, password)


def logout() -> None:
    for key in (
        "access_token",
        "token_expires_in",
        "current_user",
        "chat_session_id",
        "messages",
        "last_trace",
        "last_sources",
    ):
        st.session_state.pop(key, None)
    init_state()


def continue_as_guest() -> None:
    st.session_state.current_user = {"username": "guest", "email": "guest@local", "role": "guest"}
    st.session_state.access_token = ""
    ensure_chat_session()


def ensure_user_loaded() -> None:
    if st.session_state.get("access_token") and not st.session_state.get("current_user"):
        try:
            st.session_state.current_user = get_json("/api/v1/auth/me")
        except Exception:
            logout()


def ensure_chat_session() -> int | None:
    if st.session_state.get("chat_session_id"):
        return st.session_state.chat_session_id
    try:
        created = post_json("/api/v1/sessions", {"title": "New chat"})
        st.session_state.chat_session_id = created["id"]
        return created["id"]
    except Exception as exc:
        st.session_state.chat_session_error = str(exc)
        return None


def load_session(session_id: int) -> None:
    detail = get_json(f"/api/v1/sessions/{session_id}")
    st.session_state.chat_session_id = session_id
    st.session_state.messages = []
    for item in detail.get("messages", []):
        st.session_state.messages.append({"role": "user", "content": item.get("question", "")})
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": item.get("answer", ""),
                "sources": item.get("sources", []),
                "duration_ms": item.get("duration_ms", 0),
            }
        )
    st.session_state.active_view = "chat"


def new_chat() -> None:
    st.session_state.messages = []
    st.session_state.last_trace = []
    st.session_state.last_sources = []
    st.session_state.chat_session_id = None
    ensure_chat_session()
    st.session_state.active_view = "chat"


# ----------------------------- Styling -----------------------------
def css() -> None:
    st.markdown(
        """
<style>
    :root {
        --ink: #111827;
        --muted: #667085;
        --line: #e5e7eb;
        --soft: #f6f7fb;
        --panel: #ffffff;
        --accent: #ff4d4f;
        --accent-ink: #b42318;
        --green: #12b76a;
    }
    .stApp { background: #ffffff; color: var(--ink); }
    .block-container { max-width: 1180px; padding: 28px 34px 96px; }
    [data-testid="stSidebar"] {
        width: 330px !important;
        background: #f8fafc;
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] .block-container { padding: 22px 18px; }
    h1, h2, h3 { letter-spacing: 0 !important; }
    .brand {
        display: flex; align-items: center; gap: 10px; margin-bottom: 18px;
        font-weight: 760; font-size: 20px; color: #101828;
    }
    .brand-mark {
        width: 34px; height: 34px; border-radius: 8px; display: grid; place-items: center;
        background: #101828; color: #fff; font-weight: 800;
    }
    .login-shell {
        max-width: 980px; margin: 48px auto 0; display: grid;
        grid-template-columns: 1.05fr .95fr; gap: 34px; align-items: center;
    }
    .login-hero h1 { font-size: 46px; line-height: 1.05; margin: 0 0 12px; color: #101828; }
    .login-hero p { color: #667085; font-size: 18px; line-height: 1.65; margin: 0 0 24px; }
    .metric-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .metric-card {
        border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fff;
    }
    .metric-card b { display: block; font-size: 22px; margin-bottom: 4px; }
    .metric-card span { color: #667085; font-size: 13px; }
    .login-card {
        border: 1px solid var(--line); border-radius: 10px; background: #fff;
        padding: 24px; box-shadow: 0 18px 50px rgba(16, 24, 40, .08);
    }
    .login-card h2 { margin: 0 0 4px; font-size: 24px; }
    .login-card p { color: #667085; margin: 0 0 18px; }
    .topbar {
        display: flex; justify-content: space-between; align-items: center;
        gap: 24px; border-bottom: 1px solid var(--line); padding: 8px 0 18px; margin-bottom: 18px;
    }
    .topbar h1 { margin: 0; font-size: 28px; line-height: 1.2; }
    .topbar p { margin: 6px 0 0; color: #667085; }
    .pills { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; padding-top: 10px; }
    .pill {
        display: inline-flex; align-items: center; min-height: 34px;
        border: 1px solid #d0d5dd; border-radius: 999px; padding: 6px 12px;
        color: #344054; background: #fff; font-size: 13px; white-space: nowrap;
    }
    .pill.ok { border-color: #abefc6; background: #ecfdf3; color: #067647; }
    .hero-empty {
        margin: 38px 0 22px; padding: 8px 0 18px; max-width: 760px;
    }
    .hero-empty h2 { font-size: 34px; margin: 0 0 10px; }
    .hero-empty p { color: #667085; font-size: 16px; line-height: 1.7; }
    .prompt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }
    .prompt-card {
        border: 1px solid var(--line); border-radius: 8px; padding: 14px;
        background: #fff; color: #344054; min-height: 76px;
    }
    .section-card {
        border: 1px solid var(--line); border-radius: 8px; background: #fff;
        padding: 16px; margin-bottom: 14px;
    }
    .section-title { font-size: 18px; font-weight: 740; margin-bottom: 4px; }
    .subtle { color: #667085; font-size: 13px; }
    .session-row {
        border: 1px solid var(--line); border-radius: 8px; padding: 10px 11px;
        background: #fff; margin-bottom: 8px;
    }
    .session-row.active { border-color: #ffb4ab; background: #fff7f6; }
    .doc-row, .memory-row {
        border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 12px;
        margin-bottom: 10px;
    }
    .doc-title { font-weight: 700; word-break: break-word; }
    .status-dot {
        display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green);
        margin-right: 6px;
    }
    div[data-testid="stChatInput"] { max-width: 980px; margin: 0 auto; }
    div[data-testid="stChatMessage"] { padding: 10px 0; }
    .stButton > button {
        border-radius: 8px; min-height: 38px; font-weight: 560;
    }
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        border-radius: 8px !important;
    }
    [data-testid="stTabs"] button p { font-size: 15px; }
    @media (max-width: 900px) {
        .login-shell { grid-template-columns: 1fr; margin-top: 10px; }
        .login-hero h1 { font-size: 34px; }
        .prompt-grid { grid-template-columns: 1fr; }
        .topbar { display: block; }
        .pills { justify-content: flex-start; margin-top: 14px; }
    }
</style>
        """,
        unsafe_allow_html=True,
    )


def safe_health() -> dict:
    try:
        return get_json("/health")
    except Exception as exc:
        return {"status": "down", "error": str(exc)}


def safe_docs() -> dict:
    try:
        return get_json("/documents")
    except Exception:
        return {"documents": [], "chunks": 0, "source_count": 0}


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%m-%d %H:%M")
    except Exception:
        return value[:16]


# ----------------------------- Login view -----------------------------
def render_login(health: dict, docs: dict) -> None:
    st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True)
    hero_col, form_col = st.columns([1.1, 0.9], gap="large")
    with hero_col:
        st.markdown(
            f"""
<section class="login-hero">
  <div class="brand"><div class="brand-mark">N</div><span>NexusRAG</span></div>
  <h1>企业知识问答工作台</h1>
  <p>把本地文档、联网检索、会话历史和长期记忆放进一个清爽的对话入口。先登录，再让系统记住你的身份、偏好和工作上下文。</p>
</section>
            """,
            unsafe_allow_html=True,
        )
    with form_col:
        with st.container(border=True):
            st.subheader("登录账号")
            st.caption("登录后会隔离你的会话和长期记忆。")
            tab_login, tab_register = st.tabs(["登录", "注册"])
            with tab_login:
                with st.form("login_form", clear_on_submit=False):
                    email = st.text_input("邮箱", placeholder="name@company.com")
                    password = st.text_input("密码", type="password")
                    submitted = st.form_submit_button("登录", width="stretch", type="primary")
                if submitted:
                    try:
                        login(email.strip(), password)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            with tab_register:
                with st.form("register_form", clear_on_submit=False):
                    username = st.text_input("用户名", placeholder="你的名字或团队昵称")
                    email = st.text_input("注册邮箱", placeholder="name@company.com")
                    password = st.text_input("设置密码", type="password")
                    submitted = st.form_submit_button("注册并进入", width="stretch", type="primary")
                if submitted:
                    try:
                        register(email.strip(), username.strip(), password)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            st.divider()
            if st.button("游客体验", width="stretch"):
                continue_as_guest()
                st.rerun()


# ----------------------------- Sidebar -----------------------------
def sidebar_nav(health: dict, docs: dict) -> None:
    user = st.session_state.get("current_user") or {}
    st.sidebar.markdown('<div class="brand"><div class="brand-mark">N</div><span>NexusRAG</span></div>', unsafe_allow_html=True)
    st.sidebar.markdown(
        f"""
<div class="section-card">
  <div class="section-title">{user.get("username", "用户")}</div>
  <div class="subtle">{user.get("email", "")}</div>
  <div class="subtle" style="margin-top:8px;"><span class="status-dot"></span>{health.get("status", "ok")} · {health.get("model", "-")}</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    if st.sidebar.button("新建对话", width="stretch", type="primary"):
        new_chat()
        st.rerun()

    nav_items = {
        "chat": "对话",
        "knowledge": "知识库",
        "memory": "记忆",
        "ops": "运行状态",
    }
    selected = st.sidebar.radio(
        "工作区",
        list(nav_items.keys()),
        format_func=lambda key: nav_items[key],
        index=list(nav_items).index(st.session_state.get("active_view", "chat")),
        label_visibility="collapsed",
    )
    st.session_state.active_view = selected

    st.sidebar.divider()
    render_sidebar_sessions()
    st.sidebar.divider()
    st.sidebar.caption(f"文档 {docs.get('source_count', 0)} · 片段 {docs.get('chunks', 0)}")
    if st.sidebar.button("退出登录", width="stretch"):
        logout()
        st.rerun()


def render_sidebar_sessions() -> None:
    st.sidebar.subheader("最近会话")
    try:
        sessions = get_json("/api/v1/sessions")[:8]
    except Exception as exc:
        st.sidebar.caption(f"会话不可用：{exc}")
        return
    if not sessions:
        st.sidebar.caption("还没有会话")
        return
    active_id = st.session_state.get("chat_session_id")
    for item in sessions:
        label = item.get("title") or "New chat"
        suffix = f"{item.get('message_count', 0)} 条 · {fmt_dt(item.get('updated_at'))}"
        button_label = f"{label}\n{suffix}"
        if st.sidebar.button(button_label, key=f"session_{item['id']}", width="stretch"):
            load_session(item["id"])
            st.rerun()
        if item["id"] == active_id:
            st.sidebar.caption(f"当前：#{item['id']}")


# ----------------------------- Main shell -----------------------------
def render_topbar(health: dict, docs: dict) -> None:
    redis_ok = bool(health.get("redis", {}).get("connected"))
    st.markdown(
        f"""
<div class="topbar">
  <div>
    <h1>{view_title()}</h1>
    <p>{view_subtitle()}</p>
  </div>
  <div class="pills">
    <span class="pill">{health.get("model", "-")}</span>
    <span class="pill {'ok' if redis_ok else ''}">Redis {'已连接' if redis_ok else '未连接'}</span>
    <span class="pill">{docs.get("source_count", 0)} 文档</span>
    <span class="pill">{docs.get("chunks", 0)} 片段</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def view_title() -> str:
    return {
        "chat": "知识问答",
        "knowledge": "知识库",
        "memory": "用户记忆",
        "ops": "运行状态",
    }.get(st.session_state.get("active_view"), "知识问答")


def view_subtitle() -> str:
    return {
        "chat": "自动判断文档检索、联网检索或直接回答，并结合当前会话与长期记忆。",
        "knowledge": "管理 PDF 入库、索引状态和文档删除。",
        "memory": "查看、补充或删除系统用于个性化回答的长期记忆。",
        "ops": "查看后端、模型、检索、Embedding 与 Rerank 服务状态。",
    }.get(st.session_state.get("active_view"), "")


def render_chat() -> None:
    ensure_chat_session()
    if not st.session_state.messages:
        st.markdown(
            """
<div class="hero-empty">
  <h2>今天要查什么？</h2>
  <p>可以直接问论文、报告、产品文档，也可以问开放问题。系统会先判断是否需要知识库或联网，再生成答案。</p>
  <div class="prompt-grid">
    <div class="prompt-card">总结当前文档的核心贡献和结论</div>
    <div class="prompt-card">把这篇论文的方法、实验和局限分开列出</div>
    <div class="prompt-card">我是谁？测试长期记忆是否生效</div>
    <div class="prompt-card">需要最新信息时自动走联网检索</div>
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("sources"):
                render_sources(message["sources"])

    user_query = st.chat_input("输入问题，按 Enter 发送")
    if not user_query:
        if st.session_state.get("last_trace"):
            with st.expander("最近一次处理过程", expanded=False):
                for step in st.session_state.last_trace:
                    st.markdown(f"- {step}")
        return

    memory_before = safe_memory_keys()
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.chat_message("assistant"):
        answer_box = st.empty()
        answer = ""
        trace: list[str] = []
        sources: list[dict] = []
        try:
            for event, payload in stream_chat(user_query, st.session_state.get("chat_session_id")):
                if event == "token":
                    answer += payload.get("text", "")
                    answer_box.markdown(answer + "▌")
                elif event == "step":
                    text = payload.get("text")
                    if text:
                        trace.append(text)
                elif event == "final":
                    answer = payload.get("answer", answer)
                    trace = payload.get("agent_trace", trace)
                    sources = payload.get("sources", [])
                elif event == "error":
                    raise RuntimeError(payload.get("message", "未知错误"))
            answer_box.markdown(answer or "没有生成内容。")
            if sources:
                render_sources(sources)
            st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
            st.session_state.last_trace = trace
            st.session_state.last_sources = sources
            if memory_before != safe_memory_keys():
                st.toast("记忆已更新")
        except Exception as exc:
            answer_box.empty()
            st.error(f"请求失败：{exc}")


def safe_memory_keys() -> set[tuple[str, str]]:
    try:
        return {(m.get("memory_key", ""), m.get("content", "")) for m in get_json("/api/v1/memories?status=active")}
    except Exception:
        return set()


def render_sources(sources: list[dict]) -> None:
    with st.expander("参考来源", expanded=False):
        for source in sources[:8]:
            title = source.get("title") or source.get("source") or source.get("url") or "来源"
            url = source.get("url")
            score = source.get("score")
            page = source.get("page")
            suffix = []
            if page not in (None, "", 0):
                suffix.append(f"p.{page}")
            if score is not None:
                suffix.append(f"{float(score):.3f}")
            meta = f" · {' · '.join(suffix)}" if suffix else ""
            if url:
                st.markdown(f"- [{title}]({url}){meta}")
            else:
                st.markdown(f"- {title}{meta}")


def render_knowledge(docs: dict) -> None:
    upload_col, list_col = st.columns([0.42, 0.58], gap="large")
    with upload_col:
        st.markdown('<div class="section-title">上传文档</div><div class="subtle">支持 PDF，上传后自动切分并重建检索索引。</div>', unsafe_allow_html=True)
        file = st.file_uploader("选择 PDF", type="pdf", label_visibility="collapsed")
        async_mode = st.checkbox("后台处理", value=False)
        if st.button("上传入库", disabled=file is None, width="stretch", type="primary"):
            try:
                with st.spinner("正在处理文档..."):
                    result = upload_pdf(file, async_mode=async_mode)
                st.success(result.get("message") or "上传完成")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if st.button("重建索引", width="stretch"):
            try:
                request_json("POST", "/documents/reindex", timeout=300)
                st.success("索引已重建")
            except Exception as exc:
                st.error(str(exc))

    with list_col:
        st.markdown('<div class="section-title">已入库文档</div>', unsafe_allow_html=True)
        documents = docs.get("documents", [])
        if not documents:
            st.info("还没有文档。")
        for index, doc in enumerate(documents):
            source = doc.get("source", "")
            st.markdown(
                f"""
<div class="doc-row">
  <div class="doc-title">{source}</div>
  <div class="subtle">父块 {doc.get("parent_chunks", 0)} · 子块 {doc.get("chunks", 0)} · 上传 {doc.get("upload_count", 1)} 次</div>
</div>
                """,
                unsafe_allow_html=True,
            )
            cols = st.columns([1, 1, 2])
            confirm = cols[0].checkbox("确认删除", key=f"confirm_doc_{index}_{source}")
            if cols[1].button("删除", key=f"delete_doc_{index}_{source}", disabled=not confirm):
                try:
                    request_json("DELETE", "/documents/source", params={"source": source}, timeout=180)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def render_memory() -> None:
    add_col, list_col = st.columns([0.38, 0.62], gap="large")
    with add_col:
        st.markdown('<div class="section-title">新增记忆</div><div class="subtle">用于偏好、身份、工作上下文等长期个性化。</div>', unsafe_allow_html=True)
        with st.form("manual_memory"):
            content = st.text_area("记忆内容", placeholder="例如：以后叫我小王", height=110)
            category = st.selectbox("类型", ["preference", "identity", "profile", "work_context", "goal"])
            memory_key = st.text_input("键名", value=f"{category}.general")
            submitted = st.form_submit_button("保存记忆", width="stretch", type="primary")
        if submitted:
            try:
                post_json("/api/v1/memories", {"content": content, "category": category, "memory_key": memory_key})
                st.success("记忆已保存")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with list_col:
        st.markdown('<div class="section-title">当前记忆</div>', unsafe_allow_html=True)
        try:
            memories = get_json("/api/v1/memories?status=active")
        except Exception as exc:
            st.error(str(exc))
            memories = []
        if not memories:
            st.info("还没有长期记忆。")
        for memory in memories:
            st.markdown(
                f"""
<div class="memory-row">
  <div><b>{memory.get("content")}</b></div>
  <div class="subtle">{memory.get("category")} · {memory.get("memory_key")} · 置信度 {memory.get("confidence", 0):.2f}</div>
</div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("删除这条记忆", key=f"memory_delete_{memory.get('id')}"):
                delete_json(f"/api/v1/memories/{memory.get('id')}")
                st.rerun()
        if memories and st.button("清空全部记忆", width="stretch"):
            delete_json("/api/v1/memories")
            st.rerun()


def render_ops(health: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("后端", health.get("status", "unknown"))
    col2.metric("Redis", "connected" if health.get("redis", {}).get("connected") else "down")
    col3.metric("模型", health.get("model", "-"))
    col4.metric("环境", health.get("app_env", "-"))

    checks = {
        "模型": "/model-health",
        "检索": "/search-health",
        "Embedding": "/embedding-health",
        "Rerank": "/rerank-health",
    }
    cols = st.columns(4)
    for col, (label, path) in zip(cols, checks.items()):
        if col.button(f"检查 {label}", width="stretch"):
            try:
                col.json(get_json(path), expanded=False)
            except Exception as exc:
                col.error(str(exc))

    with st.expander("完整健康信息", expanded=False):
        st.json(health, expanded=False)

    st.subheader("任务")
    try:
        tasks = get_json("/api/v1/tasks")
        st.dataframe(tasks.get("tasks", []), width="stretch", hide_index=True)
    except Exception as exc:
        st.info(f"暂无任务或任务服务不可用：{exc}")


def main() -> None:
    st.set_page_config(page_title="NexusRAG", layout="wide", page_icon="N")
    init_state()
    css()
    ensure_user_loaded()
    health = safe_health()
    docs = safe_docs()

    if not st.session_state.get("current_user"):
        render_login(health, docs)
        return

    sidebar_nav(health, docs)
    render_topbar(health, docs)

    view = st.session_state.get("active_view", "chat")
    if view == "chat":
        render_chat()
    elif view == "knowledge":
        render_knowledge(docs)
    elif view == "memory":
        render_memory()
    else:
        render_ops(health)


if __name__ == "__main__":
    main()
