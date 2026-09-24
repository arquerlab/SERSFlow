"""Session tools (working pipeline updates allowed)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import (
    SessionCreateRequest,
    SessionPipelineUpdateRequest,
    SubsetStrategy,
)
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="post_sessions")
    async def post_sessions(
        dataset_id: str,
        pipeline: dict[str, Any] | None = None,
        subset: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /sessions — create a working session for a dataset."""

        def _run():
            pipe = Pipeline.model_validate(pipeline) if pipeline else None
            if pipe is not None:
                blocked = confirm_gates.check_fitting_components(
                    pipe,
                    max_components=ctx.config.fitting_confirm_max_components,
                    confirm=confirm,
                )
                if blocked is not None:
                    return blocked
            sub = SubsetStrategy.model_validate(subset) if subset else None
            req = SessionCreateRequest(dataset_id=dataset_id, pipeline=pipe, subset=sub)
            resp = ctx.get_client().sessions.create(req)
            return summarize.session_summary(resp)

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_sessions")
    async def get_sessions(dataset_id: str, limit: int = 50) -> str:
        """GET sessions for a dataset."""

        def _run():
            resp = ctx.get_client().sessions.list_for_dataset(dataset_id, limit=limit)
            items = [
                {
                    "session_id": i.session_id,
                    "dataset_id": i.dataset_id,
                    "created_at": i.created_at,
                    "updated_at": i.updated_at,
                }
                for i in resp.items
            ]
            return {"ok": True, "count": resp.count, "items": items}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_sessions_by_id")
    async def get_sessions_by_id(session_id: str) -> str:
        """GET /sessions/{session_id}."""

        def _run():
            return summarize.session_summary(ctx.get_client().sessions.get(session_id))

        return await tool_call(ctx, _run)

    @mcp.tool(name="put_sessions_pipeline")
    async def put_sessions_pipeline(
        session_id: str,
        pipeline: dict[str, Any],
        confirm: bool = False,
    ) -> str:
        """PUT session working pipeline (allowed; library pipelines are create-new-only)."""

        def _run():
            pipe = Pipeline.model_validate(pipeline)
            blocked = confirm_gates.check_fitting_components(
                pipe,
                max_components=ctx.config.fitting_confirm_max_components,
                confirm=confirm,
            )
            if blocked is not None:
                return blocked
            req = SessionPipelineUpdateRequest(pipeline=pipe)
            resp = ctx.get_client().sessions.update_pipeline(session_id, req)
            return {
                "ok": True,
                "session_id": session_id,
                "pipeline_hash": resp.pipeline_hash,
                "n_steps": len(resp.pipeline.steps),
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="put_sessions_subset")
    async def put_sessions_subset(session_id: str, subset: dict[str, Any]) -> str:
        """PUT session subset strategy."""

        def _run():
            sub = SubsetStrategy.model_validate(subset)
            resp = ctx.get_client().sessions.update_subset(session_id, sub)
            return {
                "ok": True,
                "session_id": session_id,
                "subset": resp.subset.model_dump(),
                "subset_hash": resp.subset_hash,
            }

        return await tool_call(ctx, _run)
