"""Regression tests that call registered FastMCP tool handlers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from sersflow.client import SersflowClient
from sersflow.mcp.config import McpConfig
from sersflow.mcp.runtime import RuntimeContext
from sersflow.mcp.server import create_server


def _ready_ctx(tmp_path: Path, transport: httpx.BaseTransport) -> RuntimeContext:
    cfg = McpConfig(
        base_url="http://test",
        export_dir=str(tmp_path / "exports"),
        api_start_enabled=False,
    )
    ctx = RuntimeContext(cfg)
    ctx.client = SersflowClient("http://test", transport=transport)
    ctx.auth_mode = "open_or_disabled"
    ctx.server_openapi_version = "0.1.0"
    ctx._ready = True
    return ctx


def _tool_fn(mcp, name: str):
    # FastMCP stores tools in mcp._tool_manager._tools (name -> Tool)
    tools = getattr(mcp, "_tool_manager", None)
    if tools is not None:
        mapping = getattr(tools, "_tools", {})
        tool = mapping.get(name)
        if tool is not None:
            return tool.fn
    # Fallback: scan attributes
    raise AssertionError(f"Tool not found: {name}")


def test_post_io_upload_confirm_not_shadowed(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/io/upload":
            return httpx.Response(200, text="Uploaded 1 file(s) to batch b1 (0.001 MB).")
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_io_upload")
    sample = tmp_path / "a.txt"
    sample.write_text("x", encoding="utf-8")

    raw = asyncio.run(fn(paths=[str(sample)], confirm=False))
    data = json.loads(raw)
    assert data.get("ok") is True, data
    assert "bool" not in str(data).lower()
    assert data.get("batch_id") == "b1"


def test_post_pipelines_overwrite_and_fitting_confirm(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pipelines" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "item": {
                        "pipeline_id": "pl1",
                        "name": "p",
                        "pipeline": {"steps": []},
                        "created_at": "t",
                        "updated_at": "t",
                    }
                },
            )
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_pipelines")

    raw = asyncio.run(fn(name="p", pipeline={"steps": []}, overwrite=True, confirm=False))
    data = json.loads(raw)
    assert data.get("ok") is False
    assert data.get("error") == "policy"

    heavy = {
        "steps": [
            {
                "name": "fitting",
                "enabled": True,
                "params": {"components": [{"component_id": f"c{i}"} for i in range(7)]},
            }
        ]
    }
    raw2 = asyncio.run(fn(name="heavy", pipeline=heavy, confirm=False))
    data2 = json.loads(raw2)
    assert data2.get("needs_confirm") is True
    assert data2.get("reason") == "fitting_components_exceed_threshold"
