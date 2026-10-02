"""Session tools (working pipeline updates allowed)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import (
    SessionCreateRequest,
    SessionPipelineUpdateRequest,
    SessionRunRequest,
    SubsetStrategy,
)
from sersflow.api.schemas.sessions_qc import SessionQcPreviewRequest
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
        """POST /sessions — create a working session for a dataset.

        Pipeline technique_family must match the dataset (vibrational or xps).
        """

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
        """PUT session working pipeline (allowed; library pipelines are create-new-only).

        technique_family must match the session dataset.
        """

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
                "technique_family": getattr(resp.pipeline, "technique_family", None),
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="put_sessions_subset")
    async def put_sessions_subset(session_id: str, subset: dict[str, Any]) -> str:
        """Update session subset strategy (HTTP POST /sessions/{id}/subset)."""

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

    @mcp.tool(name="post_sessions_qc_preview")
    async def post_sessions_qc_preview(
        session_id: str,
        step_id: str,
        scope: Literal["subset", "all"] = "subset",
        step_params: dict[str, Any] | None = None,
    ) -> str:
        """POST /sessions/{id}/qc/preview — compact QC cohort summary (no full score dumps)."""

        def _run():
            req = SessionQcPreviewRequest(
                scope=scope, step_id=step_id, step_params=step_params or {}
            )
            resp = ctx.get_client().sessions.qc_preview(session_id, req)
            data = resp.model_dump()
            scores = data.get("scores") or []
            return {
                "ok": True,
                "session_id": session_id,
                "step_id": data.get("step_id"),
                "step_name": data.get("step_name"),
                "summary": data.get("summary"),
                "threshold": data.get("threshold"),
                "direction": data.get("direction"),
                "histogram": data.get("histogram"),
                "n_scores": len(scores) if isinstance(scores, list) else 0,
                "flagged_sample": [
                    s for s in (scores if isinstance(scores, list) else []) if s.get("flagged")
                ][:20],
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_sessions_run")
    async def post_sessions_run(
        session_id: str,
        return_kind: Literal["metrics_only", "final", "intermediates"] = "metrics_only",
        metrics: list[str] | None = None,
        intermediate_steps: list[str] | None = None,
        scope: Literal["subset", "all"] = "subset",
        up_to_step: str | None = None,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /sessions/{id}/run — metrics summary by default; final/intermediates write JSON under export_dir."""

        def _run():
            if return_kind == "metrics_only":
                mets = metrics or ["rms"]
                ret: dict[str, Any] = {"kind": "metrics_only", "metrics": mets}
            elif return_kind == "intermediates":
                steps = intermediate_steps or []
                if not steps:
                    raise ValueError("intermediate_steps required when return_kind=intermediates")
                ret = {"kind": "intermediates", "steps": steps}
            else:
                ret = {"kind": "final"}
            req = SessionRunRequest.model_validate(
                {"scope": scope, "return": ret, "up_to_step": up_to_step}
            )
            data = ctx.get_client().sessions.run(session_id, req)
            if return_kind == "metrics_only":
                items = data.get("items") if isinstance(data, dict) else None
                compact = []
                if isinstance(items, list):
                    for it in items[:50]:
                        if isinstance(it, dict):
                            compact.append(
                                {
                                    "spectrum_id": it.get("spectrum_id"),
                                    "metrics": it.get("metrics"),
                                }
                            )
                return {
                    "ok": True,
                    "session_id": session_id,
                    "return_kind": return_kind,
                    "n_items": len(items) if isinstance(items, list) else 0,
                    "items": compact,
                    "truncated": isinstance(items, list) and len(items) > 50,
                }
            dest = ctx.resolve_export_path(
                output_path, f"session_{session_id}_{return_kind}.json", confirm=confirm
            )
            dest.write_text(json.dumps(data, default=str), encoding="utf-8")
            ctx.record_export(f"session_run:{session_id}", dest)
            return summarize.export_result(
                path=dest, session_id=session_id, return_kind=return_kind
            )

        return await tool_call(ctx, _run)
