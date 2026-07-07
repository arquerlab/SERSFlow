from __future__ import annotations

import io
import json
import math
import sqlite3
import zipfile
from threading import Thread
from typing import Any, Iterator, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from sersflow.api.schemas.analysis import (
    AnalysisExportManifest,
    AnalysisJobStatusResponse,
    AnalysisRunCreateRequest,
    AnalysisRunCreateResponse,
    AnalysisRunDetailResponse,
    AnalysisRunSummary,
    ObservationSchemaResponse,
)
from sersflow.api.deps import current_user_id
from sersflow.api.services.ownership import get_dataset_for_user, get_run_for_user, get_session_for_user
from sersflow.api.services.analysis_runner import execute_analysis_run, spectrum_xy_for_analysis_run
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
from sersflow.infra.analysis_store import (
    create_job,
    create_run_pending,
    delete_run,
    delete_runs_for_dataset,
    find_run_by_client_job_key,
    get_job_by_id,
    get_job_for_run,
    list_runs,
    prune_unpinned_runs,
)
from sersflow.infra.datasets_store import spectrum_export_lookup
from sersflow.infra.pipelines_store import list_pipelines
from sersflow.api.services.observation_export import (
    build_analysis_manifest,
    iter_long_feature_csv_bytes,
    iter_observation_long_csv_bytes,
    iter_observation_wide_csv_bytes,
    iter_observation_wide_dicts,
    iter_wide_feature_csv_bytes,
    list_observation_axis_and_meta_keys_for_dataset,
    write_observation_wide_parquet_bytes,
)
from sersflow.infra.sqlite_db import connect
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths

router = APIRouter(prefix="/analysis", tags=["Analysis"])


def _require_run(run_id: str, user_id: str) -> Any:
    rec = get_run_for_user(run_id, user_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return rec


# Max bytes for in-memory ZIP bundle (use separate manifest + CSV export for larger runs).
_BUNDLE_MAX_BYTES = 80 * 1024 * 1024


def _pipeline_hash_to_name_map(*, owner_user_id: str, limit: int = 500) -> dict[str, str]:
    """
    Best-effort mapping from pipeline_hash -> saved library name.
    Used to show friendly names for older runs that predate pipeline_name storage.
    """
    out: dict[str, str] = {}
    try:
        rows = list_pipelines(owner_user_id=owner_user_id, limit=limit, offset=0, q=None)
    except Exception:
        return out
    for r in rows:
        try:
            h = pipeline_hash(r.pipeline)
        except Exception:
            continue
        if h and h not in out:
            out[h] = r.name
    return out


def _pipeline_summary(pipeline_obj: Any) -> str | None:
    """
    Best-effort short label for UI tables: enabled step names joined by ' → '.
    Accepts either a Pipeline pydantic model or a dict with a `steps` list.
    """
    steps: list[Any] = []
    if pipeline_obj is None:
        return None
    if hasattr(pipeline_obj, "steps"):
        steps = list(getattr(pipeline_obj, "steps") or [])
    elif isinstance(pipeline_obj, dict):
        steps = list(pipeline_obj.get("steps") or [])
    names: list[str] = []
    for s in steps:
        try:
            enabled = True
            name = None
            if hasattr(s, "enabled"):
                enabled = bool(getattr(s, "enabled"))
            elif isinstance(s, dict):
                enabled = bool(s.get("enabled", True))
            if hasattr(s, "name"):
                name = str(getattr(s, "name"))
            elif isinstance(s, dict):
                name = str(s.get("name") or "")
            if enabled and name:
                names.append(name)
        except Exception:
            continue
    if not names:
        return None
    # Keep it compact for table cells.
    out = " \u2192 ".join(names)
    return out if len(out) <= 120 else (out[:117] + "…")


def _run_to_summary(
    rec: Any,
    *,
    owner_user_id: str,
    include_columns: bool = False,
    pipeline_name_by_hash: dict[str, str] | None = None,
) -> AnalysisRunSummary:
    cols = None
    if include_columns and rec.feature_columns_json:
        try:
            cols = json.loads(rec.feature_columns_json)
        except json.JSONDecodeError:
            cols = None
    ds_name = None
    try:
        ds = get_dataset_for_user(rec.dataset_id, owner_user_id)
        ds_name = ds.metadata.name if ds else None
    except Exception:
        ds_name = None

    pipe_sum = None
    if rec.pipeline_json:
        try:
            pipe_sum = _pipeline_summary(json.loads(rec.pipeline_json))
        except json.JSONDecodeError:
            pipe_sum = None
    if pipe_sum is None and rec.session_id:
        try:
            sess = get_session_for_user(rec.session_id, owner_user_id)
            pipe_sum = _pipeline_summary(sess.pipeline) if sess else None
        except Exception:
            pipe_sum = None

    # Prefer explicitly stored pipeline_name; otherwise try to resolve from current library.
    pipe_name = getattr(rec, "pipeline_name", None)
    if not pipe_name and pipeline_name_by_hash:
        pipe_name = pipeline_name_by_hash.get(rec.pipeline_hash)

    return AnalysisRunSummary(
        run_id=rec.run_id,
        dataset_id=rec.dataset_id,
        dataset_name=ds_name,
        session_id=rec.session_id,
        pipeline_id=getattr(rec, "pipeline_id", None),
        pipeline_name=pipe_name,
        pipeline_hash=rec.pipeline_hash,
        pipeline_summary=pipe_sum,
        subset_hash=rec.subset_hash,
        status=rec.status,
        error=rec.error,
        created_at=rec.created_at,
        finished_at=rec.finished_at,
        label=rec.label,
        pinned=rec.pinned,
        feature_columns=cols,
    )


def _idempotent_response(existing: Any) -> JSONResponse:
    j = get_job_for_run(existing.run_id)
    jid = j["job_id"] if j else None
    body = AnalysisRunCreateResponse(
        run_id=existing.run_id,
        job_id=jid,
        status=existing.status,
        message="Idempotent replay.",
    ).model_dump()
    code = 200 if existing.status == "completed" else 202
    return JSONResponse(status_code=code, content=body)


@router.post("/runs", response_model=AnalysisRunCreateResponse)
def create_analysis_run(payload: AnalysisRunCreateRequest, request: Request) -> Any:
    user_id = current_user_id(request)
    ds = get_dataset_for_user(payload.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if payload.client_job_key:
        existing = find_run_by_client_job_key(payload.client_job_key)
        if existing is not None:
            return _idempotent_response(existing)

    if payload.session_id:
        sess = get_session_for_user(payload.session_id, user_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.dataset_id != payload.dataset_id:
            raise HTTPException(status_code=400, detail="Session dataset_id does not match payload")
        pipeline = sess.pipeline
        pipeline_json = None
        params = None
    else:
        if payload.pipeline is None or payload.subset is None:
            raise HTTPException(
                status_code=400,
                detail="pipeline and subset are required when session_id is omitted",
            )
        pipeline = payload.pipeline
        pipeline_json = pipeline.model_dump_json()
        params = {"subset": payload.subset.model_dump()}

    ph = pipeline_hash(pipeline)
    # Stored cohort is always the full dataset; session.subset only affects Prepare preview.
    sh = subset_hash(SubsetStrategy(kind="all"))

    try:
        run_id = create_run_pending(
            dataset_id=payload.dataset_id,
            session_id=payload.session_id,
            pipeline_id=payload.pipeline_id,
            pipeline_name=payload.pipeline_name,
            pipeline_hash=ph,
            subset_hash=sh,
            pipeline_json=pipeline_json,
            label=payload.label,
            pinned=payload.pin,
            client_job_key=payload.client_job_key,
            params=params,
        )
    except sqlite3.IntegrityError:
        if not payload.client_job_key:
            raise HTTPException(status_code=409, detail="Insert conflict") from None
        existing = find_run_by_client_job_key(payload.client_job_key)
        if existing is None:
            raise HTTPException(status_code=409, detail="Duplicate client_job_key conflict") from None
        return _idempotent_response(existing)

    prune_unpinned_runs(dataset_id=payload.dataset_id)

    if payload.async_:
        jid = create_job(run_id=run_id)
        Thread(
            target=execute_analysis_run,
            kwargs={"run_id": run_id, "job_id": jid},
            daemon=True,
        ).start()
        return JSONResponse(
            status_code=202,
            content=AnalysisRunCreateResponse(
                run_id=run_id,
                job_id=jid,
                status="queued",
                message=None,
            ).model_dump(),
        )

    execute_analysis_run(run_id=run_id, job_id=None)
    rec = get_run_for_user(run_id, user_id)
    st = rec.status if rec else "unknown"
    return AnalysisRunCreateResponse(run_id=run_id, job_id=None, status=st, message=None)


@router.get("/runs", response_model=list[AnalysisRunSummary])
def list_analysis_runs(
    request: Request,
    dataset_id: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
) -> list[AnalysisRunSummary]:
    user_id = current_user_id(request)
    if get_dataset_for_user(dataset_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    rows = list_runs(dataset_id=dataset_id, limit=limit)
    name_by_hash = _pipeline_hash_to_name_map(owner_user_id=user_id)
    return [_run_to_summary(r, owner_user_id=user_id, include_columns=False, pipeline_name_by_hash=name_by_hash) for r in rows]


@router.get("/runs/{run_id}", response_model=AnalysisRunDetailResponse)
def get_analysis_run(run_id: str, request: Request) -> AnalysisRunDetailResponse:
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    return AnalysisRunDetailResponse(run=_run_to_summary(rec, owner_user_id=user_id, include_columns=True))


@router.delete("/runs/{run_id}", response_model=None)
def delete_analysis_run(run_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    if get_run_for_user(run_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    ok = delete_run(run_id=run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": True}


@router.delete("/runs", response_model=None)
def delete_all_analysis_runs_for_dataset(
    request: Request,
    dataset_id: str = Query(..., min_length=1, description="Delete all analysis runs for this dataset."),
) -> dict[str, Any]:
    user_id = current_user_id(request)
    if get_dataset_for_user(dataset_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    deleted = delete_runs_for_dataset(dataset_id=dataset_id)
    return {"deleted": True, "runs_deleted": int(deleted)}


@router.get("/jobs/{job_id}", response_model=AnalysisJobStatusResponse)
def get_analysis_job(job_id: str, request: Request) -> AnalysisJobStatusResponse:
    user_id = current_user_id(request)
    row = get_job_by_id(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if get_run_for_user(str(row["run_id"]), user_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return AnalysisJobStatusResponse(
        job_id=row["job_id"],
        run_id=row["run_id"],
        status=row["status"],
        progress_done=int(row["progress_done"]),
        progress_total=int(row["progress_total"]),
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _feature_keys(rec: Any) -> list[str]:
    if not rec.feature_columns_json:
        return []
    try:
        return list(json.loads(rec.feature_columns_json))
    except json.JSONDecodeError:
        return []


@router.get("/runs/{run_id}/observation-schema", response_model=ObservationSchemaResponse)
def get_observation_schema(run_id: str, request: Request) -> ObservationSchemaResponse:
    """
    Column names for pickers: extracted features from this run, dataset axes, and upload ``meta_*`` keys.
    Explore endpoints accept any numeric subset of these when merged into the observation row.
    """
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    feat = _feature_keys(rec)
    axis_keys, meta_keys = list_observation_axis_and_meta_keys_for_dataset(rec.dataset_id)
    return ObservationSchemaResponse(feature_keys=feat, axis_keys=axis_keys, meta_keys=meta_keys)


@router.get("/runs/{run_id}/observation-columns", response_model=None)
def get_observation_columns(
    run_id: str,
    request: Request,
    cols: str = Query(..., min_length=1, description="Comma-separated column names."),
    max_rows: int | None = Query(
        50_000,
        ge=1,
        le=500_000,
        description="Max spectra rows returned.",
    ),
) -> dict[str, Any]:
    """
    JSON rows for selected columns (features, ``axis_*``, ``meta_*``) — same merge as observation wide CSV.
    """
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    if rec.status != "completed":
        raise HTTPException(status_code=400, detail="Run is not completed yet")
    col_list = [c.strip() for c in cols.split(",") if c.strip()]
    if not col_list:
        raise HTTPException(status_code=400, detail="no columns requested")

    keys = _feature_keys(rec)
    lookup = spectrum_export_lookup(rec.dataset_id)
    paths = list({lookup[sid]["relative_path"] for sid in lookup if sid in lookup})
    labels_by_path: dict[str, dict[str, Any]] = {}
    if paths:
        with connect() as con:
            labels_by_path = fetch_upload_labels_for_paths(con, paths)

    rows: list[dict[str, Any]] = []
    for row in iter_observation_wide_dicts(
        run_id=run_id,
        feature_keys=keys,
        spectrum_lookup=lookup,
        labels_by_path=labels_by_path,
        join_labels=True,
        join_axes=True,
        max_rows=max_rows,
    ):
        sid = str(row["spectrum_id"])
        out: dict[str, Any] = {"spectrum_id": sid}
        info = lookup.get(sid, {})
        for c in col_list:
            if c in {"relative_path", "original_relative_path", "blob_id", "blob_relative_path"}:
                out[c] = info.get(c)
            else:
                out[c] = row.get(c)
        rows.append(out)
    return {"rows": rows}


def _json_float(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


@router.get("/runs/{run_id}/spectra/{spectrum_id}", response_model=None)
def get_analysis_spectrum(run_id: str, spectrum_id: str, request: Request) -> dict[str, Any]:
    """
    Final pipeline spectrum for one observation in a completed analysis run.
    """
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    if rec.status != "completed":
        raise HTTPException(status_code=400, detail="Run is not completed yet")

    lookup = spectrum_export_lookup(rec.dataset_id)
    info = lookup.get(spectrum_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Spectrum not found in analysis dataset")

    try:
        xy = spectrum_xy_for_analysis_run(rec=rec, spectrum_id=spectrum_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, FileNotFoundError, OSError, IndexError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    x = [_json_float(v) for v in xy.x.tolist()]
    y = [_json_float(v) for v in xy.y.tolist()]
    return {
        "spectrum_id": spectrum_id,
        "relative_path": info.get("relative_path"),
        "file_kind": info.get("file_kind"),
        "axis_time_s": info.get("axis_time_s"),
        "axis_map_x": info.get("axis_map_x"),
        "axis_map_y": info.get("axis_map_y"),
        "x": x,
        "y": y,
    }


@router.get("/runs/{run_id}/export/manifest", response_model=AnalysisExportManifest)
def get_analysis_export_manifest(run_id: str, request: Request) -> AnalysisExportManifest:
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    keys = _feature_keys(rec)
    raw = build_analysis_manifest(
        run_id=rec.run_id,
        dataset_id=rec.dataset_id,
        pipeline_hash=rec.pipeline_hash,
        subset_hash=rec.subset_hash,
        created_at=rec.created_at,
        finished_at=rec.finished_at,
        feature_columns=keys,
    )
    return AnalysisExportManifest.model_validate(raw)


@router.get("/runs/{run_id}/export/bundle", response_model=None)
def download_analysis_export_bundle(run_id: str, request: Request) -> Response:
    """
    ZIP containing `manifest.json` + `features_wide.csv` (UTF-8).
    For very large runs, use separate `/export/manifest` and streaming `/export` instead.
    """
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    if rec.status != "completed":
        raise HTTPException(status_code=400, detail="Run is not completed yet")
    keys = _feature_keys(rec)
    manifest = build_analysis_manifest(
        run_id=rec.run_id,
        dataset_id=rec.dataset_id,
        pipeline_hash=rec.pipeline_hash,
        subset_hash=rec.subset_hash,
        created_at=rec.created_at,
        finished_at=rec.finished_at,
        feature_columns=keys,
    )
    buf = io.BytesIO()
    csv_acc = io.BytesIO()
    for chunk in iter_wide_feature_csv_bytes(run_id=run_id, feature_keys=keys, max_rows=None):
        csv_acc.write(chunk)
        if csv_acc.tell() > _BUNDLE_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Bundle too large; use GET /export/manifest and GET /export?layout=wide",
            )
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        )
        zf.writestr("features_wide.csv", csv_acc.getvalue())

    payload = buf.getvalue()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="analysis_{run_id}_bundle.zip"'},
    )


def _parse_join_flags(raw: str) -> tuple[bool, bool]:
    parts = {p.strip().lower() for p in (raw or "").split(",") if p.strip()}
    return ("labels" in parts, "axes" in parts)


@router.get("/runs/{run_id}/observation", response_model=None)
def export_observation_table(
    run_id: str,
    request: Request,
    layout: Literal["wide", "long"] = Query("wide"),
    export_format: Literal["csv", "parquet"] = Query(
        "csv",
        alias="format",
        description="Wide layout only: `parquet` requires optional pyarrow (see project extras).",
    ),
    join: str = Query(
        "labels,axes",
        description="Comma-separated: labels (upload_labels), axes (time/map/grid from dataset).",
    ),
    max_rows: int | None = Query(
        None,
        ge=1,
        le=1_000_000,
        description="Max spectra rows exported.",
    ),
) -> Response | StreamingResponse:
    """
    Merged observation table: analysis features plus optional **labels** (`meta_*` columns) and **axes**
    (`axis_time_s`, `axis_map_x`, `axis_map_y`, `grid_nx`, `grid_ny`, `file_kind`).

    Use `format=parquet` with `layout=wide` for columnar export (install `pyarrow`).
    """
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    if rec.status != "completed":
        raise HTTPException(status_code=400, detail="Run is not completed yet")

    ds = get_dataset_for_user(rec.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    join_labels, join_axes = _parse_join_flags(join)
    keys = _feature_keys(rec)
    lookup = spectrum_export_lookup(rec.dataset_id)

    paths = list({lookup[sid]["relative_path"] for sid in lookup if sid in lookup})
    labels_by_path: dict[str, dict[str, Any]] = {}
    if join_labels and paths:
        with connect() as con:
            labels_by_path = fetch_upload_labels_for_paths(con, paths)

    if export_format == "parquet":
        if layout != "wide":
            raise HTTPException(status_code=400, detail="Parquet only supports layout=wide")
        try:
            payload = write_observation_wide_parquet_bytes(
                run_id=run_id,
                feature_keys=keys,
                spectrum_lookup=lookup,
                labels_by_path=labels_by_path,
                join_labels=join_labels,
                join_axes=join_axes,
                max_rows=max_rows,
            )
        except ImportError as e:
            raise HTTPException(status_code=501, detail=str(e)) from e
        return Response(
            content=payload,
            media_type="application/vnd.apache.parquet",
            headers={"Content-Disposition": f'attachment; filename="observation_{run_id}.parquet"'},
        )

    if layout == "wide":
        gen = iter_observation_wide_csv_bytes(
            run_id=run_id,
            dataset_id=rec.dataset_id,
            feature_keys=keys,
            spectrum_lookup=lookup,
            labels_by_path=labels_by_path,
            join_labels=join_labels,
            join_axes=join_axes,
            max_rows=max_rows,
        )
    else:
        gen = iter_observation_long_csv_bytes(
            run_id=run_id,
            run_id_value=rec.run_id,
            dataset_id=rec.dataset_id,
            spectrum_lookup=lookup,
            labels_by_path=labels_by_path,
            join_labels=join_labels,
            join_axes=join_axes,
            max_spectra=max_rows,
        )

    return StreamingResponse(
        gen,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="observation_{run_id}.csv"'},
    )


@router.get("/runs/{run_id}/export", response_model=None)
def export_analysis_run(
    run_id: str,
    request: Request,
    layout: Literal["wide", "long"] = Query("wide"),
    max_rows: int | None = Query(
        None,
        ge=1,
        le=1_000_000,
        description="Max spectra rows (wide) or max spectra to expand (long).",
    ),
) -> StreamingResponse:
    """
    Export features as CSV (UTF-8). Missing values are empty cells.

    **Wide layout (default):** one row per spectrum; columns are `spectrum_id` then feature columns.
    Rows are **samples** (spectra), columns are **features** for sklearn/R (numeric columns only).

    **Long layout:** `run_id`, `spectrum_id`, `feature_key`, `value`, `kind` (feature).

    For manifest + reproducibility use `GET .../export/manifest` or `GET .../export/bundle`.
    """
    user_id = current_user_id(request)
    rec = _require_run(run_id, user_id)
    if rec.status != "completed":
        raise HTTPException(status_code=400, detail="Run is not completed yet")

    keys = _feature_keys(rec)
    if layout == "wide":
        gen = iter_wide_feature_csv_bytes(run_id=run_id, feature_keys=keys, max_rows=max_rows)
    else:
        gen = iter_long_feature_csv_bytes(
            run_id=run_id,
            run_id_value=rec.run_id,
            feature_kind="feature",
            max_spectra=max_rows,
        )

    return StreamingResponse(
        gen,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="analysis_{run_id}.csv"'},
    )
