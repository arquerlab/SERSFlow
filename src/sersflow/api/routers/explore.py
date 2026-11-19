from __future__ import annotations

import json
import os
from threading import Thread
from typing import Any, Iterator

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from sersflow.api.schemas.explore import (
    ClusterRequest,
    CorrelationRequest,
    ExploreJobResponse,
    FPCADiscreteRequest,
    FPCAFDARequest,
    MatrixExportRequest,
    MatrixExportResponse,
    PCARequest,
    Spectrum2DCOSRequest,
    SpectrumClusterRequest,
    SpectrumCorrelationRequest,
    SpectrumMCRRequest,
    SpectrumNMFRequest,
    VIFRequest,
)
from sersflow.core.multivariate import (
    correlation_matrix,
    preprocess_matrix,
    reorder_correlation_result,
    rotate_pca_result,
    run_mcr_als,
    run_nmf,
    twod_cos,
)
from sersflow.api.services.explore_export import (
    iter_matrix_csv_bytes,
    iter_pca_loadings_csv_bytes,
    iter_pca_mean_csv_bytes,
    iter_pca_scores_csv_bytes,
    iter_pca_variance_csv_bytes,
    load_pca_artifact,
)
from sersflow.api.services.explore_plots import write_pca_plots
from sersflow.api.services.explore_fda import run_fpca_fda
from sersflow.api.services.explore_stats import (
    correlation_bundle,
    drop_all_nan_columns,
    load_explore_feature_matrix,
    prepare_multivariate_matrix,
    run_fpca_discrete,
    run_kmeans,
    run_kmeans_on_spectrum_matrix,
    run_pca,
    run_spca,
    save_json,
    variance_inflation_factors,
)
from sersflow.api.services.matrix_export_runner import execute_matrix_export_job, import_matrix_job_from_csv
from sersflow.api.services.observation_export import load_axis_and_meta_for_spectra
from sersflow.infra.datasets_store import spectrum_export_lookup
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
from sersflow.api.services.technique_guard import (
    dataset_technique_family,
    prepare_pipeline_for_run,
)
from sersflow.api.deps import current_user_id
from sersflow.api.services.explore_export import load_matrix_npz
from sersflow.api.services.limits import read_limited
from sersflow.api.services.ownership import (
    get_dataset_for_user,
    get_explore_run_for_user,
    get_matrix_job_for_user,
    get_run_for_user,
    get_session_for_user,
)
from sersflow.infra.explore_store import (
    artifacts_root,
    create_explore_run,
    create_matrix_job_pending,
    delete_matrix_job,
    finish_explore_run,
    list_matrix_jobs,
    prune_explore_runs,
)

router = APIRouter(prefix="/explore", tags=["Explore"])


def _artifact_subdir(*parts: str) -> str:
    return os.path.join(artifacts_root(), *parts)


def _csv_streaming_response(gen: Iterator[bytes], filename: str) -> StreamingResponse:
    first = next(gen, b"")

    def body() -> Iterator[bytes]:
        if first:
            yield first
        yield from gen

    return StreamingResponse(
        body(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _drop_columns_or_400(X: np.ndarray, names: list[str]) -> tuple[np.ndarray, list[str]]:
    """Remove columns with no finite values; map ValueError to HTTP 400."""
    try:
        return drop_all_nan_columns(X, names)
    except ValueError as e:
        msg = str(e)
        if msg == "empty matrix":
            raise HTTPException(status_code=400, detail="Empty feature matrix for the selected columns.") from e
        if msg == "shape mismatch":
            raise HTTPException(
                status_code=400,
                detail="Feature matrix shape does not match column name list.",
            ) from e
        if msg == "every column is missing for all spectra":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Every selected feature column is missing for all spectra (NaN/inf). "
                    "If you switched analysis runs, re-pick feature columns in Analyze so names match this run. "
                    "Otherwise check spectral_intensities probes in Prepare and re-run analysis."
                ),
            ) from e
        raise HTTPException(status_code=400, detail=msg) from e


def _multivariate_or_400(
    X: np.ndarray, names: list[str], spectrum_ids: list[str]
) -> tuple[np.ndarray, list[str], list[str], dict[str, Any]]:
    try:
        return prepare_multivariate_matrix(X, names, spectrum_ids)
    except ValueError as e:
        msg = str(e)
        if msg == "empty matrix":
            raise HTTPException(status_code=400, detail="Empty feature matrix for the selected columns.") from e
        if msg == "shape mismatch":
            raise HTTPException(
                status_code=400,
                detail="Feature matrix shape does not match column name list.",
            ) from e
        if msg == "every column is missing for all spectra":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Every selected feature column is missing for all spectra (NaN/inf). "
                    "If you switched analysis runs, re-pick feature columns in Analyze so names match this run. "
                    "Otherwise check spectral_intensities probes in Prepare and re-run analysis."
                ),
            ) from e
        if msg == "spectrum_ids length must match number of rows":
            raise HTTPException(status_code=500, detail="Internal error: spectrum rows mismatch.") from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.post("/matrix-jobs", response_model=MatrixExportResponse)
def post_matrix_job(payload: MatrixExportRequest, request: Request) -> MatrixExportResponse:
    user_id = current_user_id(request)
    if payload.analysis_run_id:
        rec = get_run_for_user(payload.analysis_run_id, user_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Analysis run not found")
        if rec.status != "completed":
            raise HTTPException(status_code=400, detail="Analysis run is not completed")
        if payload.dataset_id and payload.dataset_id != rec.dataset_id:
            raise HTTPException(status_code=400, detail="dataset_id does not match analysis run")
        if not rec.pipeline_json:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Analysis run does not include a stored pipeline snapshot. "
                    "Rerun the analysis with an explicit pipeline, or create the matrix job with pipeline=..."
                ),
            )
        jid = create_matrix_job_pending(
            dataset_id=rec.dataset_id,
            session_id=None,
            source_analysis_run_id=rec.run_id,
            pipeline_id=getattr(rec, "pipeline_id", None),
            pipeline_name=getattr(rec, "pipeline_name", None),
            pipeline_hash=rec.pipeline_hash,
            pipeline_json=rec.pipeline_json,
            subset_hash=rec.subset_hash,
            up_to_step=payload.up_to_step,
        )
        if payload.async_:
            Thread(target=execute_matrix_export_job, args=(jid,), daemon=True).start()
            return MatrixExportResponse(matrix_job_id=jid, status="queued")
        execute_matrix_export_job(jid)
        mj = get_matrix_job_for_user(jid, user_id)
        st = mj.status if mj else "unknown"
        return MatrixExportResponse(matrix_job_id=jid, status=st)

    if not payload.dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id is required unless analysis_run_id is provided")

    ds = get_dataset_for_user(payload.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if payload.session_id:
        sess = get_session_for_user(payload.session_id, user_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.dataset_id != payload.dataset_id:
            raise HTTPException(status_code=400, detail="dataset_id does not match session")
        pipeline = sess.pipeline
        pipeline_json = None
        session_id = payload.session_id
    else:
        if payload.pipeline is None:
            raise HTTPException(
                status_code=400,
                detail="pipeline is required when session_id is omitted",
            )
        pipeline = payload.pipeline
        pipeline_json = pipeline.model_dump_json()
        session_id = None

    pipeline = prepare_pipeline_for_run(
        pipeline,
        dataset_technique_family(ds.metadata),
        context=f"matrix job on dataset {payload.dataset_id}",
        user_id=user_id,
    )
    if pipeline_json is not None:
        pipeline_json = pipeline.model_dump_json()

    ph = pipeline_hash(pipeline)
    sh = subset_hash(SubsetStrategy(kind="all"))
    jid = create_matrix_job_pending(
        dataset_id=payload.dataset_id,
        session_id=session_id,
        source_analysis_run_id=None,
        pipeline_id=payload.pipeline_id,
        pipeline_name=payload.pipeline_name,
        pipeline_hash=ph,
        pipeline_json=pipeline_json,
        subset_hash=sh,
        up_to_step=payload.up_to_step,
    )
    if payload.async_:
        Thread(target=execute_matrix_export_job, args=(jid,), daemon=True).start()
        return MatrixExportResponse(matrix_job_id=jid, status="queued")
    execute_matrix_export_job(jid)
    mj = get_matrix_job_for_user(jid, user_id)
    st = mj.status if mj else "unknown"
    return MatrixExportResponse(matrix_job_id=jid, status=st)


@router.get("/matrix-jobs/{matrix_job_id}")
def get_matrix_job_status(matrix_job_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    mj = get_matrix_job_for_user(matrix_job_id, user_id)
    if mj is None:
        raise HTTPException(status_code=404, detail="Matrix job not found")
    manifest = json.loads(mj.manifest_json) if mj.manifest_json else None
    return {
        "matrix_job_id": mj.matrix_job_id,
        "status": mj.status,
        "dataset_id": mj.dataset_id,
        "pipeline_id": getattr(mj, "pipeline_id", None),
        "pipeline_name": getattr(mj, "pipeline_name", None),
        "analysis_run_id": getattr(mj, "source_analysis_run_id", None),
        "up_to_step": mj.up_to_step,
        "npz_path": mj.npz_path,
        "manifest": manifest,
        "error": mj.error,
        "created_at": mj.created_at,
        "finished_at": mj.finished_at,
    }


@router.get("/matrix-jobs")
def list_matrix_jobs_endpoint(
    dataset_id: str,
    request: Request,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    if get_dataset_for_user(dataset_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    items = list_matrix_jobs(dataset_id=dataset_id, limit=limit, offset=offset)
    return {
        "items": [
            {
                "matrix_job_id": it.matrix_job_id,
                "dataset_id": it.dataset_id,
                "pipeline_id": getattr(it, "pipeline_id", None),
                "pipeline_name": getattr(it, "pipeline_name", None),
                "analysis_run_id": getattr(it, "source_analysis_run_id", None),
                "up_to_step": it.up_to_step,
                "status": it.status,
                "created_at": it.created_at,
                "finished_at": it.finished_at,
                "error": it.error,
            }
            for it in items
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/matrix-jobs/{matrix_job_id}/export.csv", response_model=None)
def export_matrix_job_csv(matrix_job_id: str, request: Request) -> StreamingResponse:
    user_id = current_user_id(request)
    mj = get_matrix_job_for_user(matrix_job_id, user_id)
    if mj is None:
        raise HTTPException(status_code=404, detail="Matrix job not found")
    if mj.status != "completed" or not mj.npz_path:
        raise HTTPException(status_code=400, detail="Matrix job is not completed or has no matrix artifact")
    try:
        gen = iter_matrix_csv_bytes(mj.npz_path)
        return _csv_streaming_response(gen, f"matrix_{matrix_job_id}.csv")
    except (OSError, ValueError, KeyError) as e:
        raise HTTPException(status_code=500, detail=f"Matrix export failed: {e}") from e


@router.post("/matrix-jobs/import", response_model=MatrixExportResponse)
def import_matrix_job_csv(
    request: Request,
    dataset_id: str = Form(...),
    file: UploadFile = File(...),
    analysis_run_id: str | None = Form(None),
) -> MatrixExportResponse:
    """Import a previously exported spectrum-matrix CSV as a completed matrix job."""
    user_id = current_user_id(request)
    if get_dataset_for_user(dataset_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    run_id = (analysis_run_id or "").strip() or None
    if run_id:
        rec = get_run_for_user(run_id, user_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Analysis run not found")
        if rec.dataset_id != dataset_id:
            raise HTTPException(status_code=400, detail="analysis_run_id does not match dataset_id")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Matrix CSV file is required")
    try:
        data = read_limited(file.file, what="matrix CSV")
        if not data:
            raise ValueError("Matrix CSV file is empty")
        jid = import_matrix_job_from_csv(
            dataset_id=dataset_id,
            csv_bytes=data,
            analysis_run_id=run_id,
            source_filename=file.filename,
        )
        return MatrixExportResponse(matrix_job_id=jid, status="completed")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        try:
            file.file.close()
        except Exception:
            pass


@router.delete("/matrix-jobs/{matrix_job_id}")
def delete_matrix_job_endpoint(matrix_job_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    mj = get_matrix_job_for_user(matrix_job_id, user_id)
    if mj is None:
        raise HTTPException(status_code=404, detail="Matrix job not found")
    ok = delete_matrix_job(matrix_job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Matrix job not found")
    return {"ok": True}


def _pca_artifact_path(explore_id: str, user_id: str) -> tuple[str, str]:
    rec = get_explore_run_for_user(explore_id, user_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Explore run not found")
    if rec.status != "completed":
        raise HTTPException(status_code=400, detail="Explore run is not completed")
    names = {
        "pca": "pca.json",
        "fpca_discrete": "fpca_discrete.json",
        "fpca_fda": "fpca_fda.json",
        "nmf": "nmf.json",
        "mcr_als": "mcr_als.json",
    }
    filename = names.get(rec.kind)
    if filename is None:
        raise HTTPException(status_code=400, detail="Explore run is not a PCA artifact")
    return os.path.join(artifacts_root(), rec.artifact_subdir, filename), rec.kind


@router.get("/runs/{explore_id}/export/{export_kind}.csv", response_model=None)
def export_pca_artifact_csv(explore_id: str, export_kind: str, request: Request) -> StreamingResponse:
    user_id = current_user_id(request)
    path, _kind = _pca_artifact_path(explore_id, user_id)
    try:
        result = load_pca_artifact(path)
        if export_kind == "scores":
            spectrum_ids = result.get("spectrum_ids")
            row_ids = (
                [str(v) for v in spectrum_ids]
                if isinstance(spectrum_ids, list) and spectrum_ids
                else []
            )
            explore_rec = get_explore_run_for_user(explore_id, user_id)
            meta_cols: list[str] = []
            meta_by: dict[str, dict[str, Any]] = {}
            if explore_rec is not None and row_ids:
                meta_cols, meta_by = load_axis_and_meta_for_spectra(explore_rec.dataset_id, row_ids)
            gen = iter_pca_scores_csv_bytes(
                result,
                meta_columns=meta_cols,
                meta_by_spectrum_id=meta_by,
            )
        elif export_kind == "loadings":
            gen = iter_pca_loadings_csv_bytes(result)
        elif export_kind == "variance":
            gen = iter_pca_variance_csv_bytes(result)
        elif export_kind == "mean":
            gen = iter_pca_mean_csv_bytes(result)
        else:
            raise HTTPException(
                status_code=404,
                detail="Unknown PCA export kind; use scores, loadings, variance, or mean",
            )
        return _csv_streaming_response(gen, f"{export_kind}_{explore_id}.csv")
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=500, detail=f"PCA export failed: {e}") from e


@router.post("/correlation", response_model=ExploreJobResponse)
def post_correlation(payload: CorrelationRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    rec = get_run_for_user(payload.analysis_run_id, user_id)
    if rec is None or rec.status != "completed":
        raise HTTPException(status_code=400, detail="analysis run missing or not completed")
    keys = (
        payload.feature_columns
        if payload.feature_columns
        else (json.loads(rec.feature_columns_json) if rec.feature_columns_json else [])
    )
    if not keys:
        raise HTTPException(status_code=400, detail="no feature columns")
    X, sids, names = load_explore_feature_matrix(payload.analysis_run_id, keys)
    X, names = _drop_columns_or_400(X, names)
    result = correlation_bundle(X, names, method=payload.method)
    if payload.reorder:
        try:
            result = reorder_correlation_result(result, linkage=payload.linkage)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    subdir = f"explore/corr_{payload.analysis_run_id}"[:120]
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    save_json(os.path.join(adir, "correlation.json"), result)
    eid = create_explore_run(
        dataset_id=rec.dataset_id,
        kind="correlation",
        source_analysis_run_id=payload.analysis_run_id,
        matrix_job_id=None,
        artifact_subdir=subdir,
        input_ref={"feature_columns": names},
    )
    finish_explore_run(explore_id=eid, status="completed", error=None)
    prune_explore_runs(dataset_id=rec.dataset_id)
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result)


@router.post("/vif", response_model=ExploreJobResponse)
def post_vif(payload: VIFRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    rec = get_run_for_user(payload.analysis_run_id, user_id)
    if rec is None or rec.status != "completed":
        raise HTTPException(status_code=400, detail="analysis run missing or not completed")
    X, sids, names = load_explore_feature_matrix(payload.analysis_run_id, payload.feature_columns)
    X, names, _sids_f, meta = _multivariate_or_400(X, names, sids)
    result = variance_inflation_factors(X, names)
    result["matrix_preparation"] = meta
    subdir = f"explore/vif_{payload.analysis_run_id}"[:120]
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    save_json(os.path.join(adir, "vif.json"), result)
    eid = create_explore_run(
        dataset_id=rec.dataset_id,
        kind="vif",
        source_analysis_run_id=payload.analysis_run_id,
        matrix_job_id=None,
        artifact_subdir=subdir,
        input_ref={"feature_columns": names},
    )
    finish_explore_run(explore_id=eid, status="completed", error=None)
    prune_explore_runs(dataset_id=rec.dataset_id)
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result)


@router.post("/pca", response_model=ExploreJobResponse)
def post_pca(payload: PCARequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    rec = get_run_for_user(payload.analysis_run_id, user_id)
    if rec is None or rec.status != "completed":
        raise HTTPException(status_code=400, detail="analysis run missing or not completed")
    keys = (
        payload.feature_columns
        if payload.feature_columns
        else (json.loads(rec.feature_columns_json) if rec.feature_columns_json else [])
    )
    if not keys:
        raise HTTPException(status_code=400, detail="no feature columns")
    X, sids, names = load_explore_feature_matrix(payload.analysis_run_id, keys)
    X, names, sids_out, meta = _multivariate_or_400(X, names, sids)
    if payload.method == "spca":
        result = run_spca(
            X,
            names,
            n_components=payload.n_components,
            alpha=payload.spca_alpha,
            ridge_alpha=payload.spca_ridge_alpha,
            scaler=payload.scaler,
        )
    else:
        result = run_pca(X, names, n_components=payload.n_components, scaler=payload.scaler)
    result["matrix_preparation"] = meta
    # Align exported scores rows with stable spectrum IDs.
    result["spectrum_ids"] = list(sids_out)
    subdir = f"explore/pca_{payload.analysis_run_id}"[:120]
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    save_json(os.path.join(adir, "pca.json"), result)
    plots = write_pca_plots(adir, result)
    eid = create_explore_run(
        dataset_id=rec.dataset_id,
        kind="pca",
        source_analysis_run_id=payload.analysis_run_id,
        matrix_job_id=None,
        artifact_subdir=subdir,
        input_ref={
            "n_components": payload.n_components,
            "method": payload.method,
            "scaler": payload.scaler,
            "spca_alpha": payload.spca_alpha,
            "spca_ridge_alpha": payload.spca_ridge_alpha,
        },
    )
    finish_explore_run(explore_id=eid, status="completed", error=None)
    prune_explore_runs(dataset_id=rec.dataset_id)
    result_out = dict(result)
    result_out["plots"] = plots
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result_out)


@router.post("/fpca-discrete", response_model=ExploreJobResponse)
def post_fpca_discrete(payload: FPCADiscreteRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    mj = get_matrix_job_for_user(payload.matrix_job_id, user_id)
    if mj is None or mj.status != "completed" or not mj.npz_path:
        raise HTTPException(status_code=400, detail="matrix job not completed or npz missing")
    data = load_matrix_npz(mj.npz_path)
    Y = np.asarray(data["Y"], dtype=np.float32)
    x = np.asarray(data["x"], dtype=np.float64)
    if Y.ndim != 2 or Y.shape[0] < 2:
        raise HTTPException(status_code=400, detail="FPCA requires at least two spectra in the matrix job")
    if Y.shape[1] < 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "Matrix job produced zero wavenumber columns (Y has 0 features). "
                "This usually means the pipeline crop window does not overlap the dataset's Raman shift range. "
                "Fix crop/align, rerun the matrix job, then rerun FPCA."
            ),
        )
    sids_obj = data["spectrum_ids"]
    spectrum_ids = [str(x) for x in np.asarray(sids_obj).ravel().tolist()]
    prep_meta = None
    if payload.preprocess is not None:
        opts = payload.preprocess.model_dump()
        opts["center"] = "none"  # PCA mean-centres itself
        try:
            Y, x, prep_meta = preprocess_matrix(Y, x, opts, allow_center=False)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if payload.rotation == "varimax" and payload.method != "pca":
        raise HTTPException(status_code=400, detail="varimax rotation applies to ordinary PCA only")

    def _compute() -> dict:
        res = run_fpca_discrete(
            Y,
            x,
            spectrum_ids,
            method=payload.method,
            n_components=payload.n_components,
            spca_alpha=payload.spca_alpha,
            spca_ridge_alpha=payload.spca_ridge_alpha,
            scaler=payload.scaler,
        )
        if payload.rotation == "varimax":
            res = rotate_pca_result(res)
        return res

    if payload.run_async:  # sparse PCA on big matrices can exceed a proxy timeout
        return _dispatch_matrix_analysis(
            mj, payload.matrix_job_id, "fpca_discrete", "fpca", _compute, prep_meta, payload.model_dump(), True
        )
    result = _compute()
    if prep_meta is not None:
        result["matrix_preprocessing"] = prep_meta
    subdir = f"explore/fpca_{payload.matrix_job_id}"[:120]
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    save_json(os.path.join(adir, "fpca_discrete.json"), result)
    plots = write_pca_plots(adir, result)
    eid = create_explore_run(
        dataset_id=mj.dataset_id,
        kind="fpca_discrete",
        source_analysis_run_id=None,
        matrix_job_id=payload.matrix_job_id,
        artifact_subdir=subdir,
        input_ref={
            "matrix_job_id": payload.matrix_job_id,
            "method": payload.method,
            "n_components": payload.n_components,
            "scaler": payload.scaler,
            "spca_alpha": payload.spca_alpha,
            "spca_ridge_alpha": payload.spca_ridge_alpha,
            "rotation": payload.rotation,
            "preprocess": payload.preprocess.model_dump() if payload.preprocess else None,
        },
    )
    finish_explore_run(explore_id=eid, status="completed", error=None)
    prune_explore_runs(dataset_id=mj.dataset_id)
    result_out = dict(result)
    result_out["plots"] = plots
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result_out)


@router.post("/spectrum-cluster", response_model=ExploreJobResponse)
def post_spectrum_cluster(payload: SpectrumClusterRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    mj = get_matrix_job_for_user(payload.matrix_job_id, user_id)
    if mj is None or mj.status != "completed" or not mj.npz_path:
        raise HTTPException(status_code=400, detail="matrix job not completed or npz missing")
    data = load_matrix_npz(mj.npz_path)
    Y = np.asarray(data["Y"], dtype=np.float32)
    sids_obj = data["spectrum_ids"]
    spectrum_ids = [str(x) for x in np.asarray(sids_obj).ravel().tolist()]
    result = run_kmeans_on_spectrum_matrix(
        Y,
        spectrum_ids,
        n_clusters=payload.n_clusters,
        seed=payload.seed,
        n_pc_embedding=payload.n_pc_embedding,
    )
    subdir = f"explore/spec_cl_{payload.matrix_job_id}"[:120]
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    save_json(os.path.join(adir, "spectrum_cluster.json"), result)
    eid = create_explore_run(
        dataset_id=mj.dataset_id,
        kind="spectrum_cluster",
        source_analysis_run_id=None,
        matrix_job_id=payload.matrix_job_id,
        artifact_subdir=subdir,
        input_ref={
            "matrix_job_id": payload.matrix_job_id,
            "n_clusters": payload.n_clusters,
            "n_pc_embedding": payload.n_pc_embedding,
        },
    )
    finish_explore_run(explore_id=eid, status="completed", error=None)
    prune_explore_runs(dataset_id=mj.dataset_id)
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result)


def _load_matrix(matrix_job_id: str, user_id: str, min_rows: int = 2):
    mj = get_matrix_job_for_user(matrix_job_id, user_id)
    if mj is None or mj.status != "completed" or not mj.npz_path:
        raise HTTPException(status_code=400, detail="matrix job not completed or npz missing")
    data = load_matrix_npz(mj.npz_path)
    Y = np.asarray(data["Y"], dtype=np.float64)
    x = np.asarray(data["x"], dtype=np.float64)
    if Y.ndim != 2 or Y.shape[0] < min_rows or Y.shape[1] < 2:
        raise HTTPException(
            status_code=400,
            detail=f"matrix job needs at least {min_rows} spectra and 2 channels (got {tuple(Y.shape)})",
        )
    sids = [str(s) for s in np.asarray(data["spectrum_ids"]).ravel().tolist()]
    if x.size > 1 and not np.all(np.diff(x) > 0):
        order = np.argsort(x, kind="stable")  # channels always ascending in x
        Y, x = Y[:, order], x[order]
    return mj, Y, x, sids


def _prep(Y, x, pre, **kw):
    try:
        return preprocess_matrix(Y, x, pre.model_dump() if pre is not None else None, **kw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


_MATRIX_RESULT_FILES = {
    "spectrum_correlation": "spectrum_correlation.json",
    "nmf": "nmf.json",
    "mcr_als": "mcr_als.json",
    "cos2d": "cos2d.json",
    "fpca_discrete": "fpca_discrete.json",
}


def _dispatch_matrix_analysis(
    mj,
    matrix_job_id: str,
    kind: str,
    prefix: str,
    compute,
    meta: dict,
    input_ref: dict,
    run_async: bool,
) -> ExploreJobResponse:
    """Run ``compute()`` (the heavy part) now, or in a background thread when ``run_async``.

    Slow analyses (NMF scans, MCR-ALS on big matrices) can exceed a reverse proxy's timeout, so
    clients may start them asynchronously and poll ``GET /explore/runs/{explore_id}``.
    """
    from uuid import uuid4

    filename = _MATRIX_RESULT_FILES[kind]
    subdir = f"explore/{prefix}_{matrix_job_id}"[:100] + f"_{uuid4().hex[:8]}"
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    eid = create_explore_run(
        dataset_id=mj.dataset_id,
        kind=kind,
        source_analysis_run_id=None,
        matrix_job_id=matrix_job_id,
        artifact_subdir=subdir,
        input_ref=input_ref,
    )

    def work() -> dict:
        try:
            result = compute()
            result["matrix_preprocessing"] = meta
            save_json(os.path.join(adir, filename), result)
            finish_explore_run(explore_id=eid, status="completed", error=None)
            prune_explore_runs(dataset_id=mj.dataset_id)
            return result
        except Exception as e:  # noqa: BLE001 - recorded on the run, re-raised for the sync path
            finish_explore_run(explore_id=eid, status="failed", error=f"{type(e).__name__}: {e}")
            raise

    if run_async:

        def bg() -> None:
            try:
                work()
            except Exception:  # noqa: BLE001 - already recorded on the run
                pass

        Thread(target=bg, daemon=True, name=f"explore-{kind}-{eid}").start()
        return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results={"status": "running"})
    try:
        result = work()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result)


@router.get("/runs/{explore_id}")
def get_explore_run_result(explore_id: str, request: Request) -> dict[str, Any]:
    """Status of an explore run and, once completed, its result JSON (for async analyses)."""
    user_id = current_user_id(request)
    rec = get_explore_run_for_user(explore_id, user_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Explore run not found")
    out: dict[str, Any] = {
        "explore_id": rec.explore_id,
        "kind": rec.kind,
        "status": rec.status,
        "error": rec.error,
        "artifact_dir": os.path.join(artifacts_root(), rec.artifact_subdir),
    }
    filename = _MATRIX_RESULT_FILES.get(rec.kind)
    if rec.status == "completed" and filename:
        try:
            with open(os.path.join(artifacts_root(), rec.artifact_subdir, filename), encoding="utf-8") as fh:
                out["results"] = json.load(fh)
        except (OSError, ValueError) as e:
            raise HTTPException(status_code=500, detail=f"result unreadable: {e}") from e
    return out


@router.get("/matrix-jobs/{matrix_job_id}/spectra")
def list_matrix_job_spectra(matrix_job_id: str, request: Request, limit: int = 5000) -> dict[str, Any]:
    """Spectrum ids of a matrix job with a readable label (file, record, axes) for selection menus."""
    user_id = current_user_id(request)
    mj, _Y, _x, sids = _load_matrix(matrix_job_id, user_id, min_rows=1)
    lookup = spectrum_export_lookup(mj.dataset_id)
    items = []
    for i, sid in enumerate(sids[: max(1, min(int(limit), 20000))]):
        info = lookup.get(sid) or {}
        path = str(info.get("relative_path") or "").replace("\\", "/").split("/")[-1]
        rec_i = info.get("record_index")
        bits = [f"#{i}"]
        if path:
            bits.append(path + (f"[{rec_i}]" if rec_i not in (None, "") else ""))
        for key, tag in (("axis_z", "z"), ("axis_time_s", "t"), ("axis_map_x", "x"), ("axis_map_y", "y")):
            v = info.get(key)
            if isinstance(v, (int, float)):
                bits.append(f"{tag}={v:g}")
        items.append({"id": sid, "index": i, "label": " · ".join(bits)})
    return {"items": items, "n": len(sids), "truncated": len(sids) > len(items)}


@router.post("/spectrum-correlation", response_model=ExploreJobResponse)
def post_spectrum_correlation(payload: SpectrumCorrelationRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    mj, Y, x, sids = _load_matrix(payload.matrix_job_id, user_id, min_rows=3)
    Yp, xp, meta = _prep(Y, x, payload.preprocess, allow_center=False)
    return _dispatch_matrix_analysis(
        mj, payload.matrix_job_id, "spectrum_correlation", "spcorr",
        lambda: correlation_matrix(
            Yp, xp, sids, axis=payload.axis, method=payload.method,
            reorder=payload.reorder, linkage=payload.linkage, max_display=payload.max_display,
        ),
        meta, payload.model_dump(), payload.run_async,
    )


@router.post("/spectrum-nmf", response_model=ExploreJobResponse)
def post_spectrum_nmf(payload: SpectrumNMFRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    mj, Y, x, sids = _load_matrix(payload.matrix_job_id, user_id)
    Yp, xp, meta = _prep(Y, x, payload.preprocess, require_nonneg=True)
    return _dispatch_matrix_analysis(
        mj, payload.matrix_job_id, "nmf", "nmf",
        lambda: run_nmf(
            Yp, xp, sids, n_components=payload.n_components, n_starts=payload.n_starts,
            scan_k=payload.scan_k, seed=payload.seed,
            alpha_h=payload.alpha_h, alpha_w=payload.alpha_w, l1_ratio=payload.l1_ratio,
        ),
        meta, payload.model_dump(), payload.run_async,
    )


@router.post("/spectrum-mcr", response_model=ExploreJobResponse)
def post_spectrum_mcr(payload: SpectrumMCRRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    mj, Y, x, sids = _load_matrix(payload.matrix_job_id, user_id)
    Yp, xp, meta = _prep(Y, x, payload.preprocess, require_nonneg=True)
    for sid in payload.fixed_spectrum_ids or []:
        if str(sid) not in sids:
            raise HTTPException(status_code=400, detail=f"fixed spectrum id {sid!r} not in the matrix")
    return _dispatch_matrix_analysis(
        mj, payload.matrix_job_id, "mcr_als", "mcr",
        lambda: run_mcr_als(
            Yp, xp, sids, n_components=payload.n_components, nonneg_conc=payload.nonneg_conc,
            nonneg_spec=payload.nonneg_spec, closure=payload.closure,
            unimodal_spec=payload.unimodal_spec, normalise_spec=payload.normalise_spec,
            fixed_spectrum_ids=payload.fixed_spectrum_ids, solver=payload.solver,
            max_iter=payload.max_iter, seed=payload.seed,
        ),
        meta, payload.model_dump(), payload.run_async,
    )


@router.post("/spectrum-2dcos", response_model=ExploreJobResponse)
def post_spectrum_2dcos(payload: Spectrum2DCOSRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    mj, Y, x, sids = _load_matrix(payload.matrix_job_id, user_id, min_rows=3)
    if payload.perturbation == "observation_column":
        if not payload.analysis_run_id or not payload.perturbation_column:
            raise HTTPException(
                status_code=400,
                detail="analysis_run_id and perturbation_column are required for observation_column",
            )
        rec = get_run_for_user(payload.analysis_run_id, user_id)
        if rec is None or rec.status != "completed":
            raise HTTPException(status_code=400, detail="analysis run missing or not completed")
        Xc, csids, _names = load_explore_feature_matrix(payload.analysis_run_id, [payload.perturbation_column])
        by = {str(s): float(v) for s, v in zip(csids, Xc[:, 0])}
        t = np.array([by.get(s, np.nan) for s in sids], dtype=float)
        label = payload.perturbation_column
    else:
        t = np.arange(len(sids), dtype=float)
        label = "sample order"
    Yp, xp, meta = _prep(Y, x, payload.preprocess, allow_center=False)

    def compute() -> dict:
        result = twod_cos(
            Yp, xp, t, reference=payload.reference, perturbation_label=label, max_display=payload.max_display
        )
        result["n_spectra_without_perturbation"] = int((~np.isfinite(t)).sum())
        return result

    return _dispatch_matrix_analysis(
        mj, payload.matrix_job_id, "cos2d", "cos2d", compute, meta, payload.model_dump(), payload.run_async,
    )


@router.post("/fpca-fda", response_model=ExploreJobResponse)
def post_fpca_fda(payload: FPCAFDARequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    mj = get_matrix_job_for_user(payload.matrix_job_id, user_id)
    if mj is None or mj.status != "completed" or not mj.npz_path:
        raise HTTPException(status_code=400, detail="matrix job not completed or npz missing")
    data = load_matrix_npz(mj.npz_path)
    Y = np.asarray(data["Y"], dtype=np.float32)
    x = np.asarray(data["x"], dtype=np.float64)
    sids_obj = data["spectrum_ids"]
    spectrum_ids = [str(x) for x in np.asarray(sids_obj).ravel().tolist()]
    try:
        result = run_fpca_fda(
            Y, x, spectrum_ids, n_components=payload.n_components
        )
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    subdir = f"explore/fpca_fda_{payload.matrix_job_id}"[:120]
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    save_json(os.path.join(adir, "fpca_fda.json"), result)
    plots = write_pca_plots(adir, result)
    eid = create_explore_run(
        dataset_id=mj.dataset_id,
        kind="fpca_fda",
        source_analysis_run_id=None,
        matrix_job_id=payload.matrix_job_id,
        artifact_subdir=subdir,
        input_ref={"matrix_job_id": payload.matrix_job_id},
    )
    finish_explore_run(explore_id=eid, status="completed", error=None)
    prune_explore_runs(dataset_id=mj.dataset_id)
    result_out = dict(result)
    result_out["plots"] = plots
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result_out)


@router.post("/cluster", response_model=ExploreJobResponse)
def post_cluster(payload: ClusterRequest, request: Request) -> ExploreJobResponse:
    user_id = current_user_id(request)
    rec = get_run_for_user(payload.analysis_run_id, user_id)
    if rec is None or rec.status != "completed":
        raise HTTPException(status_code=400, detail="analysis run missing or not completed")
    keys = (
        payload.feature_columns
        if payload.feature_columns
        else (json.loads(rec.feature_columns_json) if rec.feature_columns_json else [])
    )
    if not keys:
        raise HTTPException(status_code=400, detail="no feature columns")
    X, sids, names = load_explore_feature_matrix(payload.analysis_run_id, keys)
    X, names, sids, meta = _multivariate_or_400(X, names, sids)
    result = run_kmeans(X, sids, n_clusters=payload.n_clusters, seed=payload.seed)
    result["matrix_preparation"] = meta
    # Include the spectrum IDs used for clustering (and for consistent CSV export / joins).
    result["spectrum_ids"] = list(sids)
    subdir = f"explore/cluster_{payload.analysis_run_id}"[:120]
    adir = _artifact_subdir(subdir)
    os.makedirs(adir, exist_ok=True)
    save_json(os.path.join(adir, "cluster.json"), result)
    eid = create_explore_run(
        dataset_id=rec.dataset_id,
        kind="cluster",
        source_analysis_run_id=payload.analysis_run_id,
        matrix_job_id=None,
        artifact_subdir=subdir,
        input_ref={"n_clusters": payload.n_clusters},
    )
    finish_explore_run(explore_id=eid, status="completed", error=None)
    prune_explore_runs(dataset_id=rec.dataset_id)
    return ExploreJobResponse(explore_id=eid, artifact_dir=adir, results=result)
