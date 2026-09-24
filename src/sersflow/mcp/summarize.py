"""Compact JSON summaries for MCP tool responses."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _dump(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True)
    return obj


def _shape_hint(value: Any) -> Any:
    if isinstance(value, list):
        n = len(value)
        if n == 0:
            return {"type": "list", "len": 0}
        first = value[0]
        if isinstance(first, list):
            return {"type": "matrix", "rows": n, "cols": len(first) if first else 0}
        if isinstance(first, (int, float)):
            return {"type": "vector", "len": n}
        if isinstance(first, dict):
            return {"type": "records", "len": n, "keys": list(first.keys())[:12]}
        return {"type": "list", "len": n, "item_type": type(first).__name__}
    if isinstance(value, dict):
        return {"type": "object", "keys": list(value.keys())[:20]}
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return type(value).__name__


def dataset_list_item(item: Any) -> dict[str, Any]:
    d = _dump(item)
    meta = d.get("metadata") or {}
    return {
        "dataset_id": d.get("dataset_id"),
        "name": meta.get("name") if isinstance(meta, dict) else None,
        "count": d.get("count"),
    }


def dataset_get(resp: Any) -> dict[str, Any]:
    d = _dump(resp)
    ds = d.get("dataset") or d
    spectra = ds.get("spectra") or []
    meta = ds.get("metadata") or {}
    paths = []
    for s in spectra[:5]:
        if isinstance(s, dict):
            paths.append(s.get("relative_path"))
    return {
        "ok": True,
        "dataset_id": ds.get("dataset_id"),
        "name": meta.get("name") if isinstance(meta, dict) else None,
        "n_spectra": len(spectra),
        "sample_paths": paths,
        "skipped_files": d.get("skipped_files") or [],
    }


def pipeline_list_item(item: Any) -> dict[str, Any]:
    d = _dump(item)
    pipe = d.get("pipeline") or {}
    steps = pipe.get("steps") if isinstance(pipe, dict) else None
    n_steps = len(steps) if isinstance(steps, list) else None
    return {
        "pipeline_id": d.get("pipeline_id"),
        "name": d.get("name"),
        "updated_at": d.get("updated_at"),
        "n_steps": n_steps,
    }


def session_summary(session: Any) -> dict[str, Any]:
    d = _dump(session)
    if "session" in d and isinstance(d["session"], dict):
        d = d["session"]
    pipe = d.get("pipeline") or {}
    steps = pipe.get("steps") if isinstance(pipe, dict) else []
    return {
        "ok": True,
        "session_id": d.get("session_id"),
        "dataset_id": d.get("dataset_id"),
        "n_steps": len(steps) if isinstance(steps, list) else 0,
        "subset": d.get("subset"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


def analysis_run_summary(run: Any) -> dict[str, Any]:
    d = _dump(run)
    if "run" in d and isinstance(d["run"], dict):
        d = d["run"]
    return {
        "ok": True,
        "run_id": d.get("run_id"),
        "dataset_id": d.get("dataset_id"),
        "session_id": d.get("session_id"),
        "pipeline_id": d.get("pipeline_id"),
        "pipeline_name": d.get("pipeline_name"),
        "status": d.get("status"),
        "error": d.get("error"),
        "feature_columns": d.get("feature_columns"),
        "label": d.get("label"),
        "created_at": d.get("created_at"),
        "finished_at": d.get("finished_at"),
    }


def job_summary(job: Any) -> dict[str, Any]:
    d = _dump(job)
    return {
        "ok": True,
        "job_id": d.get("job_id"),
        "run_id": d.get("run_id"),
        "status": d.get("status"),
        "progress_done": d.get("progress_done"),
        "progress_total": d.get("progress_total"),
        "error": d.get("error"),
    }


def matrix_job_summary(job: Any) -> dict[str, Any]:
    d = _dump(job) if not isinstance(job, dict) else job
    return {
        "ok": True,
        "matrix_job_id": d.get("matrix_job_id") or d.get("job_id"),
        "status": d.get("status"),
        "error": d.get("error"),
        "dataset_id": d.get("dataset_id"),
        "analysis_run_id": d.get("analysis_run_id"),
        "progress_done": d.get("progress_done"),
        "progress_total": d.get("progress_total"),
    }


def export_result(*, path: Path | str, **extra: Any) -> dict[str, Any]:
    p = Path(path)
    out: dict[str, Any] = {"ok": True, "path": str(p.resolve())}
    if p.is_file():
        out["bytes"] = p.stat().st_size
    out.update(extra)
    return out


def explore_result(resp: Any) -> dict[str, Any]:
    """Compact explore summary — no full matrices or artifact directory paths."""
    d = _dump(resp)
    results = d.get("results")
    summary: dict[str, Any] = {}
    scalars: dict[str, Any] = {}
    if isinstance(results, dict):
        summary["result_keys"] = list(results.keys())[:40]
        for key, val in results.items():
            if isinstance(val, (int, float, str, bool)) or val is None:
                scalars[key] = val
            elif key in {
                "r",
                "correlation",
                "vif",
                "n_components",
                "method",
                "scaler",
                "explained_variance_ratio",
            }:
                if isinstance(val, list) and len(val) <= 32 and all(
                    isinstance(x, (int, float)) for x in val
                ):
                    scalars[key] = val
                else:
                    summary[key] = _shape_hint(val)
            else:
                summary[f"{key}_shape"] = _shape_hint(val)
    return {
        "ok": True,
        "explore_id": d.get("explore_id"),
        "scalars": scalars,
        "summary": summary,
        "hint": "Use get_explore_runs_export / read_tabular_file for full tables; results are summarized.",
    }


def upload_result(res: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "message": getattr(res, "message", None) or str(res),
        "files_saved": getattr(res, "files_saved", None),
        "batch_id": getattr(res, "batch_id", None),
    }


def upload_list_item(item: Any) -> dict[str, Any]:
    d = _dump(item) if not isinstance(item, dict) else item
    return {
        "relative_path": d.get("relative_path") or d.get("path"),
        "filename": d.get("filename") or d.get("name"),
        "size_bytes": d.get("size_bytes") or d.get("size"),
        "batch_id": d.get("batch_id"),
    }
