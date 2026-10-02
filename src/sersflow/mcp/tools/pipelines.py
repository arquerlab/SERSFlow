"""Saved pipeline library tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.pipelines import PipelineCreateRequest, PipelineImportRequest
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_pipelines")
    async def get_pipelines(
        limit: int = 50,
        offset: int = 0,
        q: str | None = None,
        technique_family: Literal["vibrational", "xps"] | None = None,
    ) -> str:
        """GET /pipelines — list saved pipelines (optional technique_family filter)."""

        def _run():
            resp = ctx.get_client().pipelines.list(
                limit=limit, offset=offset, q=q, technique_family=technique_family
            )
            return {
                "ok": True,
                "count": resp.count,
                "items": [summarize.pipeline_list_item(i) for i in resp.items],
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_pipelines_by_id")
    async def get_pipelines_by_id(pipeline_id: str) -> str:
        """GET /pipelines/{pipeline_id}."""

        def _run():
            resp = ctx.get_client().pipelines.get(pipeline_id)
            item = resp.item
            return {
                "ok": True,
                **summarize.pipeline_list_item(item),
                "pipeline": item.pipeline.model_dump()
                if hasattr(item.pipeline, "model_dump")
                else item.pipeline,
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_pipelines")
    async def post_pipelines(
        name: str,
        pipeline: dict[str, Any],
        technique_family: Literal["vibrational", "xps"] | None = None,
        confirm: bool = False,
        overwrite: bool = False,
    ) -> str:
        """POST /pipelines — create a new named library pipeline (overwrite forbidden).

        technique_family must match the dataset you will run against (vibrational or xps).
        """

        def _run():
            blocked = confirm_gates.reject_overwrite(overwrite)
            if blocked is not None:
                return blocked
            if not (name or "").strip():
                raise ValueError("name is required for a new library pipeline")
            pipe = Pipeline.model_validate(pipeline)
            if technique_family in ("vibrational", "xps"):
                pipe = pipe.model_copy(update={"technique_family": technique_family})
            blocked = confirm_gates.check_fitting_components(
                pipe,
                max_components=ctx.config.fitting_confirm_max_components,
                confirm=confirm,
            )
            if blocked is not None:
                return blocked
            req = PipelineCreateRequest(
                name=name, pipeline=pipe, technique_family=technique_family or pipe.technique_family
            )
            resp = ctx.get_client().pipelines.create(req, overwrite=False)
            return {"ok": True, **summarize.pipeline_list_item(resp.item)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_pipelines_export")
    async def get_pipelines_export(pipeline_id: str) -> str:
        """GET /pipelines/{id}/export — return export package JSON (create-new import later)."""

        def _run():
            pkg = ctx.get_client().pipelines.export_package(pipeline_id)
            data = pkg.model_dump() if hasattr(pkg, "model_dump") else pkg
            return {"ok": True, "package": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_pipelines_import")
    async def post_pipelines_import(
        package: dict[str, Any],
        name: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /pipelines/import — import package as a new library pipeline."""

        def _run():
            body = dict(package)
            if name is not None:
                body["name"] = name
            req = PipelineImportRequest.model_validate(body)
            blocked = confirm_gates.check_fitting_components(
                req.pipeline,
                max_components=ctx.config.fitting_confirm_max_components,
                confirm=confirm,
            )
            if blocked is not None:
                return blocked
            resp = ctx.get_client().pipelines.import_package(req)
            return {"ok": True, **summarize.pipeline_list_item(resp.item)}

        return await tool_call(ctx, _run)
