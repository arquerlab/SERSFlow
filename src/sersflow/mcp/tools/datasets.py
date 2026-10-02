"""Dataset tools."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
from sersflow.mcp import confirm as confirm_gates
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
        technique_family: Literal["vibrational", "xps"] | None = None,
        vms_spectrum_mode: Literal["averages", "individuals", "all"] = "averages",
        xps_regions: list[str] | None = None,
        record_indices: dict[str, list[int]] | None = None,
    ) -> str:
        """POST /datasets — create dataset from upload relative_paths (VAMAS/XPS options supported)."""

        def _run():
            if not relative_paths:
                raise ValueError("relative_paths must be non-empty")
            meta_kw: dict[str, Any] = {
                "name": name,
                "description": description,
                "tags": tags or [],
            }
            if technique_family in ("vibrational", "xps"):
                meta_kw["technique_family"] = technique_family
            meta = DatasetMetadata(**meta_kw)
            req = DatasetCreateRequest(
                relative_paths=relative_paths,
                metadata=meta,
                vms_spectrum_mode=vms_spectrum_mode,
                xps_regions=xps_regions,
                record_indices=record_indices,
            )
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

    @mcp.tool(name="get_datasets_xps_regions")
    async def get_datasets_xps_regions(dataset_id: str) -> str:
        """GET /datasets/{dataset_id}/xps-regions."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().datasets.xps_regions(dataset_id)
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_datasets_filter_fields")
    async def get_datasets_filter_fields(dataset_id: str) -> str:
        """GET /datasets/{dataset_id}/filter-fields."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().datasets.filter_fields(dataset_id)
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_datasets_export")
    async def get_datasets_export(
        dataset_id: str,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Export dataset package ZIP to disk; returns path."""

        def _run():
            dest = ctx.resolve_export_path(
                output_path, f"dataset_{dataset_id}.zip", confirm=confirm
            )
            ctx.get_client().datasets.export_to_file(dataset_id, dest)
            ctx.record_export(f"dataset:{dataset_id}", dest)
            return summarize.export_result(path=dest, dataset_id=dataset_id, kind="package")

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_datasets_import")
    async def post_datasets_import(path: str, confirm: bool = False) -> str:
        """Import a dataset package ZIP from a local path."""

        def _run():
            p = Path(path).expanduser()
            if not p.is_file():
                raise FileNotFoundError(f"Not a file: {p}")
            if p.stat().st_size > ctx.config.upload_confirm_bytes:
                blocked = confirm_gates.require_confirm(
                    confirm,
                    reason="dataset_import_exceeds_threshold",
                    message=(
                        f"Dataset package is {p.stat().st_size} bytes > "
                        f"{ctx.config.upload_confirm_bytes}. Retry with confirm=true."
                    ),
                    details={"bytes": p.stat().st_size, "path": str(p)},
                )
                if blocked is not None:
                    return blocked
            resp = ctx.get_client().datasets.import_package(p)
            return summarize.dataset_get(resp)

        return await tool_call(ctx, _run)
