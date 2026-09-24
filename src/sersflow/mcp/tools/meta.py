"""Meta tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_health")
    async def get_health() -> str:
        """GET /health — API health check."""

        def _run():
            client = ctx.ensure_ready()
            return {"ok": True, **client.meta.health()}

        return await tool_call(ctx, _run, check_compat=False)

    @mcp.tool(name="get_mcp_meta")
    async def get_mcp_meta() -> str:
        """MCP + OpenAPI versions, auth mode, warnings, non-secret config."""

        def _run():
            return ctx.meta_payload()

        return await tool_call(ctx, _run, check_compat=False)
