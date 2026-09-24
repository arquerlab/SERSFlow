"""Saved pipeline library tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.pipelines import PipelineCreateRequest
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_pipelines")
    async def get_pipelines(limit: int = 50, offset: int = 0, q: str | None = None) -> str:
        """GET /pipelines — list saved pipelines."""

        def _run():
            resp = ctx.get_client().pipelines.list(limit=limit, offset=offset, q=q)
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
        confirm: bool = False,
        overwrite: bool = False,
    ) -> str:
        """POST /pipelines — create a new named library pipeline (overwrite forbidden)."""

        def _run():
            blocked = confirm_gates.reject_overwrite(overwrite)
            if blocked is not None:
                return blocked
            if not (name or "").strip():
                raise ValueError("name is required for a new library pipeline")
            pipe = Pipeline.model_validate(pipeline)
            blocked = confirm_gates.check_fitting_components(
                pipe,
                max_components=ctx.config.fitting_confirm_max_components,
                confirm=confirm,
            )
            if blocked is not None:
                return blocked
            req = PipelineCreateRequest(name=name, pipeline=pipe)
            resp = ctx.get_client().pipelines.create(req, overwrite=False)
            return {"ok": True, **summarize.pipeline_list_item(resp.item)}

        return await tool_call(ctx, _run)
