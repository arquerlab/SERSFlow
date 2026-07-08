from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

import numpy as np

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.core.qc.low_signal import low_signal_metric_value
from sersflow.core.qc.outliers import outlier_scores_from_xy
from sersflow.core.spectrum import XY
from sersflow.infra.datasets_store import DatasetRecord


QcStepName = Literal["low_signal_filter", "outlier_detection"]


@dataclass(frozen=True)
class QcResult:
    step_id: str | None
    step_index: int
    step_name: str
    excluded_spectrum_ids: list[str]
    scores_by_spectrum_id: dict[str, float]
    meta: dict[str, Any]


_cache = InProcessLRUCache(max_items=4096)


def is_qc_step(step: PipelineStep) -> bool:
    return bool(step.enabled) and step.name in ("low_signal_filter", "outlier_detection")


def pipeline_without_qc_steps(pipeline: Pipeline) -> Pipeline:
    steps = [s for s in pipeline.steps if not (s.enabled and s.name in ("low_signal_filter", "outlier_detection"))]
    return Pipeline(steps=[s.model_copy(deep=True) for s in steps])


def _prefix_pipeline_before_index(pipeline: Pipeline, idx: int) -> Pipeline:
    """All steps < idx, excluding QC steps (they don't transform XY)."""
    steps = []
    for s in pipeline.steps[:idx]:
        if s.enabled and s.name in ("low_signal_filter", "outlier_detection"):
            continue
        steps.append(s.model_copy(deep=True))
    return Pipeline(steps=steps)


def _finite_score(v: float) -> bool:
    return bool(np.isfinite(float(v)))


def apply_pipeline_qc_filters(
    *,
    dataset: DatasetRecord,
    pipeline: Pipeline,
    refs: list[Any],
    cache_namespace: str,
    strict: bool = True,
) -> tuple[list[Any], list[QcResult]]:
    """
    Apply QC/filter steps in pipeline order and return the filtered refs.

    Semantics:
    - Steps are treated as cohort filters (session-only): excluded spectra are removed from downstream steps.
    - QC steps do not transform XY; they only compute scores and filter the cohort.
    """
    cfg = EngineConfig(cache_namespace=cache_namespace)
    active_refs = list(refs)
    reports: list[QcResult] = []

    # Map spectrum_id -> ref for stable filtering.
    by_id: dict[str, Any] = {}
    for r in active_refs:
        sid = str(getattr(r, "spectrum_id", None) or (r.get("spectrum_id") if isinstance(r, dict) else ""))
        if sid:
            by_id[sid] = r

    for idx, step in enumerate(pipeline.steps):
        if not is_qc_step(step):
            continue
        if not active_refs:
            reports.append(
                QcResult(
                    step_id=(step.step_id or None),
                    step_index=idx,
                    step_name=step.name,
                    excluded_spectrum_ids=[],
                    scores_by_spectrum_id={},
                    meta={"note": "No spectra available at this step (cohort already empty)."},
                )
            )
            continue

        prefix = _prefix_pipeline_before_index(pipeline, idx)
        finals = run_pipeline(inputs=active_refs, pipeline=prefix, cache=_cache, config=cfg, strict=strict)

        if step.name == "low_signal_filter":
            params = dict(step.params or {})
            metric = str(params.get("metric", "median")).strip().lower()
            threshold = float(params.get("threshold", 0.0))
            percentile = params.get("percentile")
            perc_val = float(percentile) if percentile is not None else None

            scores: dict[str, float] = {}
            excluded: list[str] = []
            for sid, xy in finals.items():
                v = low_signal_metric_value(xy, metric=metric, percentile=perc_val)  # type: ignore[arg-type]
                scores[sid] = float(v)
                if not _finite_score(v) or float(v) < float(threshold):
                    excluded.append(sid)

            excluded_set = set(excluded)
            active_refs = [r for r in active_refs if str(getattr(r, "spectrum_id", "")) not in excluded_set]
            reports.append(
                QcResult(
                    step_id=(step.step_id or None),
                    step_index=idx,
                    step_name=step.name,
                    excluded_spectrum_ids=excluded,
                    scores_by_spectrum_id=scores,
                    meta={
                        "metric": metric,
                        "threshold": float(threshold),
                        "percentile": float(perc_val) if perc_val is not None else None,
                        "direction": "below",
                    },
                )
            )
            continue

        if step.name == "outlier_detection":
            params = dict(step.params or {})
            method = str(params.get("method", "correlation_to_median")).strip()
            threshold = float(params.get("threshold", 0.0))
            n_components = int(params.get("n_components", 8))
            pca_scaler = str(params.get("pca_scaler", "none")).strip().lower()

            ys_by_id: dict[str, np.ndarray] = {}
            x_by_id: dict[str, np.ndarray] = {}
            for sid, xy in finals.items():
                ys_by_id[sid] = np.asarray(xy.y, dtype=np.float64).ravel()
                x_by_id[sid] = np.asarray(xy.x, dtype=np.float64).ravel()

            scores_by_id, meta = outlier_scores_from_xy(
                method=method,  # type: ignore[arg-type]
                ys_by_id=ys_by_id,
                x_by_id=x_by_id,
                n_components=n_components,
                pca_scaler=pca_scaler,  # type: ignore[arg-type]
            )

            excluded: list[str] = []
            direction: Literal["below", "above"]
            if method == "correlation_to_median":
                direction = "below"
                for sid, v in scores_by_id.items():
                    if not _finite_score(v) or float(v) < float(threshold):
                        excluded.append(sid)
            else:
                direction = "above"
                for sid, v in scores_by_id.items():
                    if not _finite_score(v) or float(v) > float(threshold):
                        excluded.append(sid)

            excluded_set = set(excluded)
            active_refs = [r for r in active_refs if str(getattr(r, "spectrum_id", "")) not in excluded_set]
            reports.append(
                QcResult(
                    step_id=(step.step_id or None),
                    step_index=idx,
                    step_name=step.name,
                    excluded_spectrum_ids=excluded,
                    scores_by_spectrum_id={k: float(v) for k, v in scores_by_id.items()},
                    meta={
                        **meta,
                        "threshold": float(threshold),
                        "direction": direction,
                        "n_components": int(n_components),
                        "pca_scaler": pca_scaler,
                    },
                )
            )
            continue

    return active_refs, reports


def apply_pipeline_qc_filters_before_step(
    *,
    dataset: DatasetRecord,
    pipeline: Pipeline,
    refs: list[Any],
    cache_namespace: str,
    stop_before_step_index: int,
    strict: bool = True,
) -> tuple[list[Any], list[QcResult]]:
    """
    Apply QC/filter steps for indices < stop_before_step_index, then return remaining refs.
    """
    clipped = Pipeline(steps=[s.model_copy(deep=True) for s in pipeline.steps[: max(0, int(stop_before_step_index))]])
    return apply_pipeline_qc_filters(
        dataset=dataset,
        pipeline=clipped,
        refs=refs,
        cache_namespace=cache_namespace,
        strict=strict,
    )


def qc_step_xy_inputs(
    *,
    pipeline: Pipeline,
    refs: list[Any],
    cache_namespace: str,
    step_index: int,
    strict: bool = True,
) -> dict[str, XY]:
    """Helper for preview: run prefix pipeline and return XY at that stage."""
    cfg = EngineConfig(cache_namespace=cache_namespace)
    prefix = _prefix_pipeline_before_index(pipeline, step_index)
    return run_pipeline(inputs=refs, pipeline=prefix, cache=_cache, config=cfg, strict=strict)

