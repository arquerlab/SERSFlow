"""Dataset tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="post_datasets")
    async def post_datasets(
        relative_paths: list[str],
        name: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
    ) -> str:
        """POST /datasets — create dataset from upload relative_paths."""

        def _run():
            if not relative_paths:
                raise ValueError("relative_paths must be non-empty")
            meta = DatasetMetadata(name=name, description=description, tags=tags or [])
            req = DatasetCreateRequest(relative_paths=relative_paths, metadata=meta)
            resp = ctx.get_client().datasets.create(req)
            return summarize.dataset_get(resp)

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_datasets")
    async def get_datasets(limit: int = 50, offset: int = 0) -> str:
        """GET /datasets — list datasets."""

        def _run():
            resp = ctx.get_client().datasets.list(limit=limit, offset=offset)
            return {
                "ok": True,
                "count": resp.count,
                "items": [summarize.dataset_list_item(i) for i in resp.items],
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_datasets_by_id")
    async def get_datasets_by_id(dataset_id: str) -> str:
        """GET /datasets/{dataset_id}."""

        def _run():
            return summarize.dataset_get(ctx.get_client().datasets.get(dataset_id))

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_datasets_spectrum_axes")
    async def get_datasets_spectrum_axes(
        dataset_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> str:
        """GET /datasets/{dataset_id}/spectrum-axes."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().datasets.spectrum_axes(dataset_id, limit=limit, offset=offset)
            return {"ok": True, **data}

        return await tool_call(ctx, _run)
