"""X3: MCP tools for backend features that had no MCP access (run spectra, step outputs, edit/delete)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.pipelines import PipelineUpdateRequest
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_analysis_runs_spectrum")
    async def get_analysis_runs_spectrum(run_id: str, spectrum_id: str, max_points: int = 0) -> str:
        """GET /analysis/runs/{run_id}/spectra/{spectrum_id} - the final pipeline x/y of one observation of a completed run.

        max_points > 0 thins the arrays (evenly spaced) to keep the reply small; 0 returns everything.
        """

        def _run():
            data = ctx.get_client().analysis.get_spectrum(run_id, spectrum_id)
            x, y = list(data.get("x") or []), list(data.get("y") or [])
            n = len(x)
            if max_points and n > max_points > 1:
                idx = [round(i * (n - 1) / (max_points - 1)) for i in range(max_points)]
                data = {**data, "x": [x[i] for i in idx], "y": [y[i] for i in idx], "thinned_from": n}
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_analysis_runs_pipeline_steps")
    async def get_analysis_runs_pipeline_steps(run_id: str) -> str:
        """GET /analysis/runs/{run_id}/pipeline-steps - enabled steps numbered as post_analysis_step_outputs_jobs expects."""

        def _run():
            data = ctx.get_client().analysis.get_pipeline_steps(run_id)
            return {"ok": True, "run_id": run_id, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_analysis_step_outputs_jobs")
    async def post_analysis_step_outputs_jobs(
        run_id: str, step_nums: list[int], spectrum_ids: list[str] | None = None
    ) -> str:
        """POST /analysis/runs/{run_id}/step-outputs-jobs - zip with the raw XY and the output of each chosen pipeline step.

        step_nums come from get_analysis_runs_pipeline_steps; spectrum_ids=None exports every spectrum of the run.
        Wait with post_analysis_fit_curve_jobs_wait, then download with get_analysis_fit_curve_jobs_download.
        """

        def _run():
            resp = ctx.get_client().analysis.create_step_outputs_job(run_id, step_nums, spectrum_ids)
            return {"ok": True, "job_id": resp.job_id, "status": resp.status, "run_id": run_id}

        return await tool_call(ctx, _run)

    @mcp.tool(name="put_pipelines_by_id")
    async def put_pipelines_by_id(
        pipeline_id: str,
        pipeline: dict[str, Any] | None = None,
        name: str | None = None,
        technique_family: str | None = None,
        confirm: bool = False,
    ) -> str:
        """PUT /pipelines/{pipeline_id} - REPLACE a saved library pipeline (and/or rename it). Needs confirm=true.

        This overwrites the stored steps; prefer post_pipelines (new name) when the old version might be needed.
        """

        def _run():
            client = ctx.get_client()
            current = client.pipelines.get(pipeline_id).item
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Overwriting a saved pipeline",
                details={
                    "pipeline_id": pipeline_id,
                    "current_name": current.name,
                    "new_name": name,
                    "replaces_steps": pipeline is not None,
                    "current_step_count": len(getattr(current.pipeline, "steps", []) or []),
                },
            )
            if blocked is not None:
                return blocked
            pipe = Pipeline.model_validate(pipeline) if pipeline is not None else None
            if pipe is not None:
                blocked = confirm_gates.check_fitting_components(
                    pipe, max_components=ctx.config.fitting_confirm_max_components, confirm=confirm
                )
                if blocked is not None:
                    return blocked
            req = PipelineUpdateRequest(name=name, pipeline=pipe, technique_family=technique_family)
            resp = client.pipelines.update(pipeline_id, req)
            item = resp.item
            return {"ok": True, "pipeline_id": item.pipeline_id, "name": item.name, "technique_family": item.technique_family}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_pipelines_by_id")
    async def delete_pipelines_by_id(pipeline_id: str, confirm: bool = False) -> str:
        """DELETE /pipelines/{pipeline_id} - permanently delete a saved library pipeline. Needs confirm=true."""

        def _run():
            client = ctx.get_client()
            item = client.pipelines.get(pipeline_id).item
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Deleting a saved pipeline",
                details={"pipeline_id": pipeline_id, "name": item.name, "technique_family": item.technique_family},
            )
            if blocked is not None:
                return blocked
            return {"ok": True, **client.pipelines.delete(pipeline_id)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_datasets_by_id")
    async def delete_datasets_by_id(dataset_id: str, confirm: bool = False) -> str:
        """DELETE /datasets/{dataset_id} - remove a dataset and its sessions (runs of it become unreachable). Needs confirm=true."""

        def _run():
            client = ctx.get_client()
            ds = client.datasets.get(dataset_id).dataset
            runs = client.analysis.list_runs(dataset_id, limit=200)
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Deleting a dataset",
                details={
                    "dataset_id": dataset_id,
                    "name": ds.metadata.name,
                    "spectra": len(ds.spectra),
                    "analysis_runs": len(runs),
                },
            )
            if blocked is not None:
                return blocked
            return {"ok": True, **client.datasets.delete(dataset_id)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_analysis_runs_by_id")
    async def delete_analysis_runs_by_id(run_id: str, confirm: bool = False) -> str:
        """DELETE /analysis/runs/{run_id} - delete one analysis run and its exports. Needs confirm=true."""

        def _run():
            client = ctx.get_client()
            run = client.analysis.get_run(run_id).run
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Deleting an analysis run",
                details={
                    "run_id": run_id,
                    "dataset_id": getattr(run, "dataset_id", None),
                    "status": getattr(run, "status", None),
                },
            )
            if blocked is not None:
                return blocked
            return {"ok": True, **client.analysis.delete_run(run_id)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_analysis_runs")
    async def delete_analysis_runs(dataset_id: str, confirm: bool = False) -> str:
        """DELETE /analysis/runs?dataset_id= - delete EVERY analysis run of a dataset. Needs confirm=true."""

        def _run():
            client = ctx.get_client()
            runs = client.analysis.list_runs(dataset_id, limit=200)
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Deleting all analysis runs of a dataset",
                details={"dataset_id": dataset_id, "run_count": len(runs), "run_ids": [r.run_id for r in runs[:50]]},
            )
            if blocked is not None:
                return blocked
            return {"ok": True, **client.analysis.delete_all_runs(dataset_id)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_explore_matrix_jobs")
    async def delete_explore_matrix_jobs(matrix_job_id: str, confirm: bool = False) -> str:
        """DELETE /explore/matrix-jobs/{id} - delete a matrix export job. Needs confirm=true."""

        def _run():
            client = ctx.get_client()
            job = client.explore.get_matrix_job(matrix_job_id)
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Deleting a matrix job",
                details={"matrix_job_id": matrix_job_id, "dataset_id": job.get("dataset_id"), "status": job.get("status")},
            )
            if blocked is not None:
                return blocked
            return {"ok": True, **client.explore.delete_matrix_job(matrix_job_id)}

        return await tool_call(ctx, _run)
