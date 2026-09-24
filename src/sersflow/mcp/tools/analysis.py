"""Analysis run / job / export tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sersflow.api.schemas.analysis import AnalysisRunCreateRequest
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.client import SersflowClient
    from sersflow.mcp.runtime import RuntimeContext


def _resolve_pipeline_by_name(client: SersflowClient, name: str) -> Any:
    resp = client.pipelines.list(limit=100, q=name)
    matches = [i for i in resp.items if (i.name or "").strip() == name.strip()]
    if not matches:
        raise ValueError(f"No library pipeline named {name!r}")
    if len(matches) > 1:
        ids = [m.pipeline_id for m in matches]
        raise ValueError(f"Ambiguous pipeline name {name!r}; matches ids={ids}. Use pipeline_id.")
    return matches[0].pipeline


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="post_analysis_runs")
    async def post_analysis_runs(
        dataset_id: str,
        session_id: str | None = None,
        pipeline_id: str | None = None,
        pipeline_name: str | None = None,
        pipeline: dict[str, Any] | None = None,
        subset: dict[str, Any] | None = None,
        label: str | None = None,
        pin: bool = False,
        client_job_key: str | None = None,
        async_: bool | None = None,
        confirm: bool = False,
    ) -> str:
        """
        POST /analysis/runs — start feature extraction (async default from TOML).

        Provide session_id OR (pipeline + subset). pipeline_id/pipeline_name are labels unless
        used for fitting confirm resolution; they do not alone load a pipeline for the run.
        """

        def _run():
            client = ctx.get_client()
            pipe_obj = Pipeline.model_validate(pipeline) if pipeline else None
            if not session_id and pipe_obj is None:
                raise ValueError(
                    "Provide session_id or an inline pipeline (+ subset). "
                    "pipeline_id/pipeline_name alone do not supply the run pipeline."
                )
            if pipe_obj is not None and subset is None and not session_id:
                raise ValueError("Inline pipeline requires subset (e.g. {\"kind\": \"all\"}).")

            if pipe_obj is not None:
                blocked = confirm_gates.check_fitting_components(
                    pipe_obj,
                    max_components=ctx.config.fitting_confirm_max_components,
                    confirm=confirm,
                )
                if blocked is not None:
                    return blocked
            elif pipeline_id:
                lib = client.pipelines.get(pipeline_id)
                blocked = confirm_gates.check_fitting_components(
                    lib.item.pipeline,
                    max_components=ctx.config.fitting_confirm_max_components,
                    confirm=confirm,
                )
                if blocked is not None:
                    return blocked
            elif pipeline_name and not session_id:
                named = _resolve_pipeline_by_name(client, pipeline_name)
                blocked = confirm_gates.check_fitting_components(
                    named,
                    max_components=ctx.config.fitting_confirm_max_components,
                    confirm=confirm,
                )
                if blocked is not None:
                    return blocked
            elif session_id:
                sess = client.sessions.get(session_id)
                blocked = confirm_gates.check_fitting_components(
                    sess.session.pipeline,
                    max_components=ctx.config.fitting_confirm_max_components,
                    confirm=confirm,
                )
                if blocked is not None:
                    return blocked

            use_async = ctx.config.analysis_async_default if async_ is None else async_
            sub = SubsetStrategy.model_validate(subset) if subset else None
            req = AnalysisRunCreateRequest(
                dataset_id=dataset_id,
                session_id=session_id,
                pipeline_id=pipeline_id,
                pipeline_name=pipeline_name,
                pipeline=pipe_obj,
                subset=sub,
                async_=use_async,
                label=label,
                pin=pin,
                client_job_key=client_job_key,
            )
            resp = client.analysis.create_run(req)
            return {
                "ok": True,
                "run_id": resp.run_id,
                "job_id": resp.job_id,
                "status": resp.status,
                "message": resp.message,
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs")
    async def get_analysis_runs(dataset_id: str, limit: int = 50) -> str:
        """GET analysis runs for a dataset."""

        def _run():
            runs = ctx.get_client().analysis.list_runs(dataset_id, limit=limit)
            return {
                "ok": True,
                "items": [summarize.analysis_run_summary(r) for r in runs],
                "count": len(runs),
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs_by_id")
    async def get_analysis_runs_by_id(run_id: str) -> str:
        """GET /analysis/runs/{run_id}."""

        def _run():
            return summarize.analysis_run_summary(ctx.get_client().analysis.get_run(run_id))

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_jobs")
    async def get_analysis_jobs(job_id: str) -> str:
        """GET /analysis/jobs/{job_id} — poll job status."""

        def _run():
            return summarize.job_summary(ctx.get_client().analysis.get_job(job_id))

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_analysis_jobs_wait")
    async def post_analysis_jobs_wait(
        job_id: str,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> str:
        """Wait for an analysis job (timeout from TOML unless overridden)."""

        def _run():
            job = ctx.get_client().analysis.wait_for_job(
                job_id,
                timeout_s=timeout_s if timeout_s is not None else ctx.config.job_wait_timeout_s,
                poll_interval_s=(
                    poll_interval_s
                    if poll_interval_s is not None
                    else ctx.config.job_poll_interval_s
                ),
            )
            return summarize.job_summary(job)

        return await tool_call(
            ctx,
            _run,
            status_tool="get_analysis_jobs",
            wait_tool="post_analysis_jobs_wait",
        )

    @mcp.tool(name="get_analysis_runs_export_manifest")
    async def get_analysis_runs_export_manifest(run_id: str) -> str:
        """GET /analysis/runs/{run_id}/export/manifest."""

        def _run():
            man = ctx.get_client().analysis.export_manifest(run_id)
            data = man.model_dump() if hasattr(man, "model_dump") else man
            cached = ctx.export_paths.get(f"analysis:{run_id}", [])
            return {"ok": True, "manifest": data, "local_export_paths": cached}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs_export")
    async def get_analysis_runs_export(
        run_id: str,
        output_path: str | None = None,
        layout: Literal["wide", "long"] = "wide",
        max_rows: int | None = None,
        confirm: bool = False,
    ) -> str:
        """Export analysis feature table CSV to disk; returns path (no preview)."""

        def _run():
            dest = ctx.resolve_export_path(
                output_path, f"analysis_{run_id}_features.csv", confirm=confirm
            )
            ctx.get_client().analysis.export_features_to_file(
                run_id, dest, layout=layout, max_rows=max_rows
            )
            ctx.record_export(f"analysis:{run_id}", dest)
            return summarize.export_result(path=dest, run_id=run_id, kind="features")

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs_observation")
    async def get_analysis_runs_observation(
        run_id: str,
        output_path: str | None = None,
        layout: Literal["wide", "long"] = "wide",
        format: Literal["csv", "parquet"] = "csv",
        join: str = "labels,axes",
        max_rows: int | None = None,
        confirm: bool = False,
    ) -> str:
        """Export observation table to disk; returns path (no preview)."""

        def _run():
            ext = "parquet" if format == "parquet" else "csv"
            dest = ctx.resolve_export_path(
                output_path, f"analysis_{run_id}_observation.{ext}", confirm=confirm
            )
            ctx.get_client().analysis.export_observation_to_file(
                run_id,
                dest,
                layout=layout,
                format=format,
                join=join,
                max_rows=max_rows,
            )
            ctx.record_export(f"analysis:{run_id}", dest)
            return summarize.export_result(path=dest, run_id=run_id, kind="observation")

        return await tool_call(ctx, _run)
