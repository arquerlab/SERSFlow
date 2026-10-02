"""FastMCP server factory for SpecFlow."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from sersflow.mcp.resources import register_resources
from sersflow.mcp.runtime import RuntimeContext, configure_stderr_logging
from sersflow.mcp.tools import register_all


def create_server(ctx: RuntimeContext | None = None) -> FastMCP:
    """Build the stdio MCP server with tools and resources registered."""
    configure_stderr_logging()
    runtime = ctx or RuntimeContext.from_env()
    mcp = FastMCP("SpecFlow")
    register_all(mcp, runtime)
    register_resources(mcp, runtime)
    return mcp
