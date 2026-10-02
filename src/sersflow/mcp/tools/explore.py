"""Explore / matrix tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sersflow.api.schemas.explore import (
    CorrelationRequest,
    FPCADiscreteRequest,
    MatrixExportRequest,
    PCARequest,
    VIFRequest,
)
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def _validate_matrix_args(
    *,
    dataset_id: str | None,
    analysis_run_id: str | None,
    session_id: str | None,
    pipeline: dict[str, Any] | None,
) -> None:
    if analysis_run_id:
        return
    if dataset_id and (session_id or pipeline):
        return
    raise ValueError(
        "Matrix job requires analysis_run_id, or dataset_id plus (session_id or inline pipeline). "
        "pipeline_id/pipeline_name are labels only and do not load a library pipeline by themselves."
    )


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="post_explore_correlation")
    async def post_explore_correlation(
        analysis_run_id: str,
        feature_columns: list[str] | None = None,
    ) -> str:
        """POST /explore/correlation (returns compact summary; export for full tables)."""

        def _run():
            req = CorrelationRequest(analysis_run_id=analysis_run_id, feature_columns=feature_columns)
            return summarize.explore_result(ctx.get_client().explore.correlation(req))

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_explore_vif")
    async def post_explore_vif(analysis_run_id: str, feature_columns: list[str]) -> str:
        """POST /explore/vif (compact summary)."""

        def _run():
            req = VIFRequest(analysis_run_id=analysis_run_id, feature_columns=feature_columns)
            return summarize.explore_result(ctx.get_client().explore.vif(req))

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_explore_pca")
    async def post_explore_pca(
        analysis_run_id: str,
        n_components: int | None = None,
        feature_columns: list[str] | None = None,
        method: Literal["pca", "spca"] = "pca",
        scaler: Literal["none", "standard"] = "none",
        spca_alpha: float = 1.0,
        spca_ridge_alpha: float = 1e-5,
    ) -> str:
        """POST /explore/pca (method pca|spca); compact summary."""

        def _run():
            req = PCARequest(
                analysis_run_id=analysis_run_id,
                n_components=n_components,
                feature_columns=feature_columns,
                method=method,
                scaler=scaler,
                spca_alpha=spca_alpha,
                spca_ridge_alpha=spca_ridge_alpha,
            )
            return summarize.explore_result(ctx.get_client().explore.pca(req))

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_explore_runs_export")
    async def get_explore_runs_export(
        explore_id: str,
        kind: Literal["scores", "loadings", "variance", "mean"],
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """GET /explore/runs/{id}/export/{kind}.csv → file path."""

        def _run():
            dest = ctx.resolve_export_path(
                output_path, f"explore_{explore_id}_{kind}.csv", confirm=confirm
            )
            ctx.get_client().explore.export_pca_csv_to_file(explore_id, kind, dest)
            ctx.record_export(f"explore:{explore_id}", dest)
            return summarize.export_result(path=dest, explore_id=explore_id, kind=kind)

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_explore_matrix_jobs")
    async def post_explore_matrix_jobs(
        dataset_id: str | None = None,
        analysis_run_id: str | None = None,
        session_id: str | None = None,
        pipeline_id: str | None = None,
        pipeline_name: str | None = None,
        pipeline: dict[str, Any] | None = None,
        up_to_step: str | None = None,
        async_: bool | None = None,
        confirm: bool = False,
    ) -> str:
        """
        POST /explore/matrix-jobs.

        Requires analysis_run_id OR dataset_id+(session_id|inline pipeline).
        pipeline_id/pipeline_name are labels only.
        Dataset and pipeline technique_family must match when a pipeline is supplied.
        """

        def _run():
            _validate_matrix_args(
                dataset_id=dataset_id,
                analysis_run_id=analysis_run_id,
                session_id=session_id,
                pipeline=pipeline,
            )
            client = ctx.get_client()
            pipe = Pipeline.model_validate(pipeline) if pipeline else None
            if pipe is not None:
                blocked = confirm_gates.check_fitting_components(
                    pipe,
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
            req = MatrixExportRequest(
                dataset_id=dataset_id,
                analysis_run_id=analysis_run_id,
                session_id=session_id,
                pipeline_id=pipeline_id,
                pipeline_name=pipeline_name,
                pipeline=pipe,
                up_to_step=up_to_step,
                async_=use_async,
            )
            resp = client.explore.create_matrix_job(req)
            return {
                "ok": True,
                "matrix_job_id": resp.matrix_job_id,
                "status": resp.status,
            }

        return await tool_call(
            ctx,
            _run,
            status_tool="get_explore_matrix_jobs",
            wait_tool="post_explore_matrix_jobs_wait",
        )

    @mcp.tool(name="get_explore_matrix_jobs")
    async def get_explore_matrix_jobs(matrix_job_id: str) -> str:
        """GET /explore/matrix-jobs/{matrix_job_id}."""

        def _run():
            data = ctx.get_client().explore.get_matrix_job(matrix_job_id)
            return summarize.matrix_job_summary(data)

        return await tool_call(
            ctx,
            _run,
            status_tool="get_explore_matrix_jobs",
            wait_tool="post_explore_matrix_jobs_wait",
        )

    @mcp.tool(name="post_explore_matrix_jobs_wait")
    async def post_explore_matrix_jobs_wait(
        matrix_job_id: str,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> str:
        """Wait for a matrix job to complete."""

        def _run():
            data = ctx.get_client().explore.wait_for_matrix_job(
                matrix_job_id,
                timeout_s=timeout_s if timeout_s is not None else ctx.config.job_wait_timeout_s,
                poll_interval_s=(
                    poll_interval_s
                    if poll_interval_s is not None
                    else ctx.config.job_poll_interval_s
                ),
            )
            return summarize.matrix_job_summary(data)

        return await tool_call(
            ctx,
            _run,
            status_tool="get_explore_matrix_jobs",
            wait_tool="post_explore_matrix_jobs_wait",
        )

    @mcp.tool(name="get_explore_matrix_jobs_export")
    async def get_explore_matrix_jobs_export(
        matrix_job_id: str,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Export matrix job CSV to disk."""

        def _run():
            dest = ctx.resolve_export_path(
                output_path, f"matrix_{matrix_job_id}.csv", confirm=confirm
            )
            ctx.get_client().explore.export_matrix_to_file(matrix_job_id, dest)
            ctx.record_export(f"matrix:{matrix_job_id}", dest)
            return summarize.export_result(path=dest, matrix_job_id=matrix_job_id)

        return await tool_call(
            ctx,
            _run,
            status_tool="get_explore_matrix_jobs",
            wait_tool="post_explore_matrix_jobs_wait",
        )

    @mcp.tool(name="post_explore_fpca_discrete")
    async def post_explore_fpca_discrete(
        matrix_job_id: str,
        method: Literal["pca", "spca"] = "pca",
        n_components: int | None = None,
        scaler: Literal["none", "standard"] = "none",
        spca_alpha: float = 1.0,
        spca_ridge_alpha: float = 1e-5,
    ) -> str:
        """POST /explore/fpca-discrete — spectrum-matrix PCA/sPCA (compact summary)."""

        def _run():
            req = FPCADiscreteRequest(
                matrix_job_id=matrix_job_id,
                method=method,
                n_components=n_components,
                scaler=scaler,
                spca_alpha=spca_alpha,
                spca_ridge_alpha=spca_ridge_alpha,
            )
            return summarize.explore_result(ctx.get_client().explore.fpca_discrete(req))

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_explore_matrix_jobs_list")
    async def get_explore_matrix_jobs_list(
        dataset_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> str:
        """GET /explore/matrix-jobs — list matrix jobs for a dataset."""

        def _run():
            data = ctx.get_client().explore.list_matrix_jobs(
                dataset_id, limit=limit, offset=offset
            )
            items = data.get("items") or []
            compact = []
            for it in items if isinstance(items, list) else []:
                if isinstance(it, dict):
                    compact.append(summarize.matrix_job_summary(it))
            return {"ok": True, "count": data.get("count", len(compact)), "items": compact}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_explore_matrix_jobs_import")
    async def post_explore_matrix_jobs_import(
        dataset_id: str,
        path: str,
        analysis_run_id: str | None = None,
    ) -> str:
        """POST /explore/matrix-jobs/import — import a spectrum-matrix CSV as a completed job."""

        def _run():
            from pathlib import Path

            p = Path(path).expanduser()
            if not p.is_file():
                raise FileNotFoundError(f"Not a file: {p}")
            resp = ctx.get_client().explore.import_matrix_job(
                dataset_id, p, analysis_run_id=analysis_run_id
            )
            return {
                "ok": True,
                "matrix_job_id": resp.matrix_job_id,
                "status": resp.status,
                "dataset_id": dataset_id,
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_explore_cluster")
    async def post_explore_cluster(
        analysis_run_id: str,
        feature_columns: list[str] | None = None,
        n_clusters: int = 3,
        seed: int = 0,
    ) -> str:
        """POST /explore/cluster (compact summary)."""

        def _run():
            from sersflow.api.schemas.explore import ClusterRequest

            req = ClusterRequest(
                analysis_run_id=analysis_run_id,
                n_clusters=n_clusters,
                feature_columns=feature_columns,
                seed=seed,
            )
            return summarize.explore_result(ctx.get_client().explore.cluster(req))

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_explore_spectrum_cluster")
    async def post_explore_spectrum_cluster(
        matrix_job_id: str,
        n_clusters: int = 3,
        seed: int = 0,
        n_pc_embedding: int = 10,
    ) -> str:
        """POST /explore/spectrum-cluster (compact summary)."""

        def _run():
            from sersflow.api.schemas.explore import SpectrumClusterRequest

            req = SpectrumClusterRequest(
                matrix_job_id=matrix_job_id,
                n_clusters=n_clusters,
                seed=seed,
                n_pc_embedding=n_pc_embedding,
            )
            return summarize.explore_result(ctx.get_client().explore.spectrum_cluster(req))

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_explore_fpca_fda")
    async def post_explore_fpca_fda(
        matrix_job_id: str,
        n_components: int | None = None,
    ) -> str:
        """POST /explore/fpca-fda (compact summary)."""

        def _run():
            from sersflow.api.schemas.explore import FPCAFDARequest

            req = FPCAFDARequest(matrix_job_id=matrix_job_id, n_components=n_components)
            return summarize.explore_result(ctx.get_client().explore.fpca_fda(req))

        return await tool_call(ctx, _run)
