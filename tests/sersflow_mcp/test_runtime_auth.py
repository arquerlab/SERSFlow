"""Runtime auth and API ensure tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from sersflow.client import SersflowClient
from sersflow.client.exceptions import SersflowApiError
from sersflow.mcp.config import McpConfig
from sersflow.mcp.runtime import RuntimeContext


def test_authenticate_cookie(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/auth/login":
            return httpx.Response(
                200,
                json={"user": {"user_id": "u1", "username": "alice", "is_superuser": False}},
                headers={"set-cookie": "sersflow_session=tok"},
            )
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json={"info": {"version": "0.1.0", "title": "SpecFlow API"}})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "nope"})

    transport = httpx.MockTransport(handle)
    cfg = McpConfig(
        base_url="http://test",
        username="alice",
        password="pw",
        export_dir=str(tmp_path / "exp"),
        api_start_enabled=False,
    )
    ctx = RuntimeContext(cfg)
    with patch.object(ctx, "health_ok", return_value=True):
        client = SersflowClient("http://test", transport=transport)
        ctx.client = client
        ctx.authenticate()
        ctx.version_probe()
        ctx._ready = True
    assert ctx.auth_mode == "cookie"
    assert ctx.version_incompatible is False
    assert any(c.startswith("POST /auth/login") for c in calls)


def test_authenticate_open_mode(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/datasets":
            return httpx.Response(200, json={"items": [], "count": 0})
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    cfg = McpConfig(base_url="http://test", export_dir=str(tmp_path / "exp"), api_start_enabled=False)
    ctx = RuntimeContext(cfg)
    ctx.client = SersflowClient("http://test", transport=transport)
    ctx.authenticate()
    assert ctx.auth_mode == "open_or_disabled"


def test_authenticate_401_message(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Not authenticated"})

    transport = httpx.MockTransport(handle)
    cfg = McpConfig(base_url="http://test", export_dir=str(tmp_path / "exp"))
    ctx = RuntimeContext(cfg)
    ctx.client = SersflowClient("http://test", transport=transport)
    with pytest.raises(RuntimeError, match="SERSFLOW_USERNAME"):
        ctx.authenticate()


def test_ensure_api_spawns_when_down(tmp_path: Path) -> None:
    cfg = McpConfig(
        base_url="http://127.0.0.1:18999",
        export_dir=str(tmp_path / "exp"),
        api_start_enabled=True,
        api_health_timeout_s=2.0,
        api_health_poll_s=0.05,
    )
    ctx = RuntimeContext(cfg)
    health_calls = {"n": 0}

    def health_ok() -> bool:
        health_calls["n"] += 1
        return health_calls["n"] >= 3

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 12345

    with (
        patch.object(ctx, "health_ok", side_effect=health_ok),
        patch("sersflow.mcp.runtime.subprocess.Popen", return_value=fake_proc) as popen,
    ):
        ctx.ensure_api()
    assert ctx.spawned_by_mcp is True
    popen.assert_called_once()
    assert "uvicorn" in popen.call_args[0][0]
    # Re-entry while healthy must not clear ownership
    with patch.object(ctx, "health_ok", return_value=True):
        ctx.ensure_api()
    assert ctx.spawned_by_mcp is True


def test_incompatible_major_version(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json={"info": {"version": "1.0.0", "title": "X"}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    cfg = McpConfig(base_url="http://test", export_dir=str(tmp_path / "exp"))
    ctx = RuntimeContext(cfg)
    ctx.client = SersflowClient("http://test", transport=transport)
    ctx.version_probe()
    assert ctx.version_incompatible is True
    bad = ctx.require_compatible()
    assert bad is not None
    assert bad["error"] == "incompatible"
