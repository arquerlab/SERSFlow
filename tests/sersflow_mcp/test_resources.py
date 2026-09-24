"""Resource handlers run off the event loop via asyncio.to_thread."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

from sersflow.mcp.config import McpConfig
from sersflow.mcp.runtime import RuntimeContext
from sersflow.mcp.server import create_server


def test_pipelines_resource_async_offload(tmp_path: Path) -> None:
    cfg = McpConfig(
        base_url="http://test",
        export_dir=str(tmp_path / "exports"),
        api_start_enabled=False,
    )
    ctx = RuntimeContext(cfg)
    item = MagicMock()
    item.model_dump.return_value = {
        "pipeline_id": "pl1",
        "name": "demo",
        "pipeline": {"steps": [{"name": "baseline"}]},
        "updated_at": "t",
    }
    resp = MagicMock()
    resp.count = 1
    resp.items = [item]
    ctx.client = MagicMock()
    ctx.client.pipelines.list.return_value = resp
    ctx.auth_mode = "open_or_disabled"
    ctx.server_openapi_version = "0.1.0"
    ctx._ready = True

    mcp = create_server(ctx)
    resource = mcp._resource_manager._resources["sersflow://pipelines"]
    assert asyncio.iscoroutinefunction(resource.fn)

    raw = asyncio.run(resource.read())
    data = json.loads(raw)
    assert data.get("count") == 1
    assert data["items"][0]["pipeline_id"] == "pl1"
    assert data["items"][0]["n_steps"] == 1
    assert "steps" not in data["items"][0]


def test_resource_errors_are_structured_json(tmp_path: Path) -> None:
    cfg = McpConfig(
        base_url="http://test",
        export_dir=str(tmp_path / "exports"),
        api_start_enabled=False,
    )
    ctx = RuntimeContext(cfg)
    ctx.client = MagicMock()
    ctx.client.pipelines.list.side_effect = RuntimeError("boom")
    ctx.auth_mode = "open_or_disabled"
    ctx.server_openapi_version = "0.1.0"
    ctx._ready = True

    mcp = create_server(ctx)
    resource = mcp._resource_manager._resources["sersflow://pipelines"]
    raw = asyncio.run(resource.read())
    data = json.loads(raw)
    assert data.get("ok") is False
    assert data.get("error") == "runtime"
    assert "boom" in str(data.get("message"))
