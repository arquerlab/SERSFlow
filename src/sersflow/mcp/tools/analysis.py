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
        Dataset and pipeline technique_family must match (vibrational or xps).
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

    @mcp.tool(name="get_analysis_runs_observation_schema")
    async def get_analysis_runs_observation_schema(run_id: str) -> str:
        """GET /analysis/runs/{run_id}/observation-schema."""

        def _run():
            schema = ctx.get_client().analysis.observation_schema(run_id)
            data = schema.model_dump() if hasattr(schema, "model_dump") else schema
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs_observation_columns")
    async def get_analysis_runs_observation_columns(
        run_id: str,
        cols: str,
        max_rows: int | None = 500,
    ) -> str:
        """GET observation column slice (keep max_rows modest for context size)."""

        def _run():
            data = ctx.get_client().analysis.observation_columns(
                run_id, cols, max_rows=max_rows
            )
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs_export_bundle")
    async def get_analysis_runs_export_bundle(
        run_id: str,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Download analysis export bundle ZIP to export_dir."""

        def _run():
            dest = ctx.resolve_export_path(
                output_path, f"analysis_{run_id}_bundle.zip", confirm=confirm
            )
            ctx.get_client().analysis.export_bundle_to_file(run_id, dest)
            ctx.record_export(f"analysis:{run_id}", dest)
            return summarize.export_result(path=dest, run_id=run_id, kind="bundle")

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs_fitting_steps")
    async def get_analysis_runs_fitting_steps(run_id: str) -> str:
        """GET /analysis/runs/{run_id}/fitting-steps."""

        def _run():
            data = ctx.get_client().analysis.fitting_steps(run_id)
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_analysis_runs_fitting_preview")
    async def post_analysis_runs_fitting_preview(
        run_id: str,
        spectrum_ids: list[str],
        fitting_step_num: int,
        return_curve: bool = False,
    ) -> str:
        """POST fitting preview (compact; default return_curve=false)."""

        def _run():
            from sersflow.api.schemas.analysis import FittingPreviewRequest

            req = FittingPreviewRequest(
                spectrum_ids=spectrum_ids,
                fitting_step_num=fitting_step_num,
                return_curve=return_curve,
            )
            data = ctx.get_client().analysis.fitting_preview(run_id, req)
            # Compact: drop large curve arrays unless explicitly requested
            if not return_curve and isinstance(data, dict):
                items = data.get("items") or data.get("previews") or []
                if isinstance(items, list):
                    compact_items = []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        compact_items.append(
                            {
                                k: v
                                for k, v in it.items()
                                if k
                                not in {
                                    "x",
                                    "y",
                                    "y_fit",
                                    "residual",
                                    "components",
                                    "curve",
                                }
                            }
                        )
                    data = {**data, "items": compact_items}
            return {"ok": True, "data": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_analysis_fit_curve_jobs")
    async def post_analysis_fit_curve_jobs(
        run_id: str,
        fitting_step_num: int,
        content: Literal["data_fit_resid", "data_fit_components_resid"] = "data_fit_components_resid",
        format: Literal["csv", "png", "svg"] = "csv",
    ) -> str:
        """POST /analysis/runs/{run_id}/fit-curve-jobs."""

        def _run():
            from sersflow.api.schemas.analysis import FitCurveJobCreateRequest

            req = FitCurveJobCreateRequest(
                fitting_step_num=fitting_step_num, content=content, format=format
            )
            resp = ctx.get_client().analysis.create_fit_curve_job(run_id, req)
            return {
                "ok": True,
                "job_id": resp.job_id,
                "status": resp.status,
                "run_id": run_id,
            }

        return await tool_call(
            ctx,
            _run,
            status_tool="get_analysis_fit_curve_jobs",
            wait_tool="post_analysis_fit_curve_jobs_wait",
        )

    @mcp.tool(name="get_analysis_fit_curve_jobs")
    async def get_analysis_fit_curve_jobs(job_id: str) -> str:
        """GET /analysis/fit-curve-jobs/{job_id}."""

        def _run():
            job = ctx.get_client().analysis.get_fit_curve_job(job_id)
            return summarize.job_summary(job)

        return await tool_call(
            ctx,
            _run,
            status_tool="get_analysis_fit_curve_jobs",
            wait_tool="post_analysis_fit_curve_jobs_wait",
        )

    @mcp.tool(name="post_analysis_fit_curve_jobs_wait")
    async def post_analysis_fit_curve_jobs_wait(
        job_id: str,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> str:
        """Wait for a fit-curve export job."""

        def _run():
            job = ctx.get_client().analysis.wait_for_fit_curve_job(
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
            status_tool="get_analysis_fit_curve_jobs",
            wait_tool="post_analysis_fit_curve_jobs_wait",
        )

    @mcp.tool(name="get_analysis_fit_curve_jobs_download")
    async def get_analysis_fit_curve_jobs_download(
        job_id: str,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Download completed fit-curve job ZIP to export_dir."""

        def _run():
            dest = ctx.resolve_export_path(
                output_path, f"fit_curves_{job_id}.zip", confirm=confirm
            )
            ctx.get_client().analysis.export_fit_curve_job_to_file(job_id, dest)
            ctx.record_export(f"fit_curve:{job_id}", dest)
            return summarize.export_result(path=dest, job_id=job_id, kind="fit_curves")

        return await tool_call(ctx, _run)
