"""IO upload tools."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.io import (
    AutoLabelsRequest,
    PurgePreviewRequest,
    PurgeRequest,
    UnloadRequest,
    UpdateLabelsRequest,
)
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
        folder_pattern: str = "*",
    ) -> str:
        """POST /io/upload — upload local files or a folder (paths).

        Folder default pattern is ``*`` (all files). Requires confirm=true if >100MB.
        """

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

    @mcp.tool(name="get_io_unloaded")
    async def get_io_unloaded(limit: int = 100) -> str:
        """GET /io/unloaded — list unloaded uploads."""

        def _run():
            data = ctx.get_client().io.list_unloaded(limit=limit)
            dumped = data.model_dump() if hasattr(data, "model_dump") else data
            items = dumped.get("items") or []
            return {
                "ok": True,
                "count": dumped.get("count", len(items)),
                "items": [
                    {
                        "relative_path": i.get("relative_path") if isinstance(i, dict) else getattr(i, "relative_path", None),
                        "filename": i.get("filename") if isinstance(i, dict) else getattr(i, "filename", None),
                        "size_bytes": i.get("size_bytes") if isinstance(i, dict) else getattr(i, "size_bytes", None),
                    }
                    for i in (items[:50] if isinstance(items, list) else [])
                ],
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_io_unload")
    async def post_io_unload(relative_paths: list[str]) -> str:
        """POST /io/unload — mark uploads unloaded (not purge)."""

        def _run():
            msg = ctx.get_client().io.unload(UnloadRequest(relative_paths=relative_paths))
            return {"ok": True, "message": msg}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_io_purge_preview")
    async def post_io_purge_preview(
        relative_paths: list[str] | None = None,
        hidden_only: bool = True,
    ) -> str:
        """POST /io/purge/preview — preview purge candidates."""

        def _run():
            req = PurgePreviewRequest(relative_paths=relative_paths, hidden_only=hidden_only)
            resp = ctx.get_client().io.purge_preview(req)
            data = resp.model_dump()
            return {
                "ok": True,
                "total_files": data.get("total_files"),
                "total_size_bytes": data.get("total_size_bytes"),
                "blocked": data.get("blocked"),
                "missing": data.get("missing"),
                "n_items": len(data.get("items") or []),
                "items_sample": (data.get("items") or [])[:20],
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_io_purge")
    async def post_io_purge(relative_paths: list[str], confirm: bool = False) -> str:
        """POST /io/purge — permanently delete uploads. Always requires confirm=true."""

        def _run():
            blocked = confirm_gates.require_confirm(
                confirm,
                reason="purge_requires_confirm",
                message="Purge permanently deletes upload files. Retry with confirm=true after user approval.",
                details={"n_paths": len(relative_paths)},
            )
            if blocked is not None:
                return blocked
            resp = ctx.get_client().io.purge(PurgeRequest(relative_paths=relative_paths))
            return {"ok": True, **resp.model_dump()}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_io_labels_auto")
    async def post_io_labels_auto(relative_paths: list[str]) -> str:
        """POST /io/labels/auto — auto-extract labels for uploads."""

        def _run():
            data = ctx.get_client().io.auto_labels(AutoLabelsRequest(relative_paths=relative_paths))
            return {"ok": True, **(data if isinstance(data, dict) else {"result": data})}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_io_labels_update")
    async def post_io_labels_update(
        relative_path: str,
        labels: dict[str, Any],
        record_index: int | None = None,
    ) -> str:
        """PUT/POST /io/labels — merge labels (supports XPS block record_index)."""

        def _run():
            req = UpdateLabelsRequest(
                relative_path=relative_path, labels=labels, record_index=record_index
            )
            data = ctx.get_client().io.update_labels(req)
            return {"ok": True, **(data if isinstance(data, dict) else {"result": data})}

        return await tool_call(ctx, _run)
