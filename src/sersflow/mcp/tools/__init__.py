"""Register all MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sersflow.mcp.tools import (
    analysis,
    datasets,
    explore,
    fitting,
    io_tools,
    meta,
    pipelines,
    sessions,
    tabular,
    xps_recipes,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register_all(mcp: FastMCP, ctx: RuntimeContext) -> None:
    meta.register(mcp, ctx)
    io_tools.register(mcp, ctx)
    datasets.register(mcp, ctx)
    sessions.register(mcp, ctx)
    pipelines.register(mcp, ctx)
    fitting.register(mcp, ctx)
    xps_recipes.register(mcp, ctx)
    analysis.register(mcp, ctx)
    explore.register(mcp, ctx)
    tabular.register(mcp, ctx)
