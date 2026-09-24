"""Fitting catalog (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_fitting_models")
    async def get_fitting_models() -> str:
        """GET /fitting/models — read-only fitting catalog."""

        def _run():
            resp = ctx.get_client().fitting.models()
            return {"ok": True, "data": resp.model_dump() if hasattr(resp, "model_dump") else resp}

        return await tool_call(ctx, _run)
