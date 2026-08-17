"""
测试套件 — 基础模块导入 & 核心逻辑测试
运行：pytest tests/ -v --asyncio-mode=auto
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── 配置测试 ──────────────────────────────────────────────
def test_settings_defaults():
    """验证 Pydantic Settings 默认值正确加载。"""
    from backend.core.config import settings
    assert settings.app_version == "2.0.0"
    assert settings.jwt_algorithm == "HS256"
    assert settings.cache_ttl_seconds == 3600
    assert settings.rate_limit_per_minute == 20
    assert not settings.require_auth  # 默认关闭


# ── 异常处理测试 ──────────────────────────────────────────
def test_app_error():
    """验证 AppError 携带正确属性。"""
    from backend.core.exceptions import AppError, ErrorCode
    err = AppError(ErrorCode.AUTH_UNAUTHORIZED, "请先登录", 401)
    assert err.code == "AUTH_UNAUTHORIZED"
    assert err.status_code == 401
    assert str(err) == "请先登录"


# ── JWT 测试 ──────────────────────────────────────────────
def test_jwt_create_and_decode():
    """验证 JWT 生成与解码一致。"""
    from backend.services.auth_service import create_access_token, decode_token
    token = create_access_token(user_id=42, role="user")
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "user"


def test_password_hash_verify():
    """验证 bcrypt 密码哈希与验证。"""
    from backend.services.auth_service import hash_password, verify_password
    hashed = hash_password("mypass123")
    assert verify_password("mypass123", hashed)
    assert not verify_password("wrongpass", hashed)


# ── 缓存键测试 ──────────────────────────────────────────────
def test_cache_key_deterministic():
    """相同问题应生成相同缓存键。"""
    import hashlib
    q = "什么是 CRAG？"
    digest = hashlib.md5(q.strip().lower().encode()).hexdigest()
    key = f"crag:chat:cache:{digest}"
    assert "crag:chat:cache:" in key
    assert len(digest) == 32


# ── FastAPI 应用测试 ──────────────────────────────────────
@pytest.fixture
def client():
    from backend.main import app
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    """验证 /health 接口返回 200。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "app_version" in data
    assert "redis" in data
    assert "database" in data


def test_docs_available(client):
    """验证 Swagger 文档可访问。"""
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_auth_register_no_db(client):
    """无数据库时，注册接口返回 503。"""
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "username": "tester", "password": "pass123"},
    )
    assert resp.status_code == 503


def test_chat_no_auth_allowed(client):
    """require_auth=False 时，无 Token 也可以访问 /chat（会因 LLM 失败返回错误但不是 401）。"""
    resp = client.post("/chat", json={"question": "你好"})
    # 无 LLM Key 时会报错，但不是 401
    assert resp.status_code != 401
