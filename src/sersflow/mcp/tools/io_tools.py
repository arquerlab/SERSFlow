"""IO upload tools."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="post_io_upload")
    async def post_io_upload(
        paths: list[str],
        base_dir: str | None = None,
        confirm: bool = False,
        folder_pattern: str = "*.txt",
    ) -> str:
        """POST /io/upload — upload local files or a folder (paths). Requires confirm=true if >100MB."""

        def _run():
            if not paths:
                raise ValueError("paths must be non-empty")
            resolved = [Path(p).expanduser() for p in paths]
            is_single_dir = len(resolved) == 1 and resolved[0].is_dir()
            blocked = confirm_gates.check_upload_size(
                resolved,
                threshold=ctx.config.upload_confirm_bytes,
                confirm=confirm,
                folder_pattern=folder_pattern if is_single_dir else None,
            )
            if blocked is not None:
                return blocked
            client = ctx.get_client()
            if is_single_dir:
                res = client.io.upload_folder(
                    resolved[0],
                    pattern=folder_pattern,
                    recursive=True,
                    base_dir=base_dir or resolved[0],
                )
            else:
                for p in resolved:
                    if not p.is_file():
                        raise FileNotFoundError(f"Not a file: {p}")
                res = client.io.upload_files(resolved, base_dir=base_dir)
            return summarize.upload_result(res)

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_io_uploads")
    async def get_io_uploads(limit: int = 100) -> str:
        """GET /io/uploads — list uploaded files (short summary)."""

        def _run():
            data = ctx.get_client().io.list_uploads(limit=limit)
            dumped = data.model_dump() if hasattr(data, "model_dump") else data
            items = dumped.get("items") or []
            summarized = [summarize.upload_list_item(i) for i in items[:50]]
            return {
                "ok": True,
                "count": dumped.get("count", len(items)),
                "items": summarized,
                "truncated": isinstance(items, list) and len(items) > 50,
            }

        return await tool_call(ctx, _run)
