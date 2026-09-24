"""Shared helpers for MCP tool handlers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, TypeVar

from sersflow.mcp.errors import exception_to_payload
from sersflow.mcp.runtime import RuntimeContext

T = TypeVar("T")


async def run_sync(fn: Callable[[], T]) -> T:
    return await asyncio.to_thread(fn)


def json_result(data: Any) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)


async def tool_call(
    ctx: RuntimeContext,
    fn: Callable[[], Any],
    *,
    status_tool: str = "get_analysis_jobs",
    wait_tool: str = "post_analysis_jobs_wait",
    check_compat: bool = True,
) -> str:
    """
    Run a sync tool body off the event loop.

    ``ensure_ready`` (health/spawn/login) also runs in the worker thread so
    long API startup does not block the MCP asyncio loop.
    """

    def _wrapped() -> Any:
        ctx.ensure_ready()
        if check_compat:
            bad = ctx.require_compatible()
            if bad is not None:
                return bad
        return fn()

    try:
        out = await run_sync(_wrapped)
        if isinstance(out, str):
            return out
        return json_result(out)
    except Exception as e:
        return json_result(
            exception_to_payload(e, status_tool=status_tool, wait_tool=wait_tool)
        )
