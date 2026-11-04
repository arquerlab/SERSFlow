from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.core.qc.low_signal import low_signal_metric_value
from sersflow.core.qc.outliers import outlier_scores_from_xy
from sersflow.core.spectrum import XY
from sersflow.infra.datasets_store import DatasetRecord


QcStepName = Literal["low_signal_filter", "outlier_detection"]

# Session cohort QC only. metadata_filter is an engine XY mask (branch-local), not cohort QC.
_QC_NAMES = ("low_signal_filter", "outlier_detection")
# Cohort step that replaces the working set with group averages (derived spectra).
GROUP_STEP_NAME = "group_average"
_COHORT_NAMES = (*_QC_NAMES, GROUP_STEP_NAME)


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
    return bool(step.enabled) and step.name in _COHORT_NAMES


def _with_steps(pipeline: Pipeline, steps: list) -> Pipeline:
    """Rebuild pipeline steps while preserving technique_family and other top-level fields."""
    return pipeline.model_copy(update={"steps": steps})


def first_group_step_index(pipeline: Pipeline) -> int | None:
    """Index of the first enabled group_average step, or None."""
    return next((i for i, s in enumerate(pipeline.steps) if s.enabled and s.name == GROUP_STEP_NAME), None)


def view_is_after_group(pipeline: Pipeline, group_idx: int, token: str | None) -> bool:
    """
    Whether the requested view shows aggregated spectra (at/after the group step) rather than raw ones.

    ``token`` is a session-run view: None / final (whole pipeline) -> aggregated; ``__source__`` -> raw;
    ``__raw__`` -> aggregated; ``__raw__:N`` (cohort steps through N) -> aggregated when N reaches the group
    step; ``name`` / ``name__N`` -> by the position of that step.
    """
    t = str(token or "").strip()
    if not t:
        return True
    if t == "__source__":
        return False
    if t == "__raw__":
        return True
    if t.startswith("__raw__:"):
        try:
            return int(t.split(":", 1)[1]) > group_idx
        except ValueError:
            return True
    idx = step_index_for_token(pipeline, t)
    return True if idx is None else idx >= group_idx


def step_index_for_token(pipeline: Pipeline, token: str) -> int | None:
    """Index of the pipeline step a view token (``name`` or ``name__N``) refers to, or None."""
    from sersflow.core.pipeline.engine import _parse_collect_token
    from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums

    name, num = _parse_collect_token(str(token or "").strip())
    nums = assign_pipeline_step_nums(pipeline.steps)
    for i, s in enumerate(pipeline.steps):
        if s.name == name and (num is None or nums[i] == num):
            return i
    return None


def _last_group_index(pipeline: Pipeline, before: int | None = None) -> int | None:
    """Index of the last enabled group_average step (strictly before ``before`` when given)."""
    end = len(pipeline.steps) if before is None else max(0, int(before))
    for i in range(end - 1, -1, -1):
        s = pipeline.steps[i]
        if s.enabled and s.name == GROUP_STEP_NAME:
            return i
    return None


def pipeline_without_qc_steps(pipeline: Pipeline) -> Pipeline:
    """
    Pipeline the XY engine runs after cohort steps were applied to the refs.

    Cohort steps are removed. Steps before the last ``group_average`` were already applied to produce
    the averages, so they stay in place but disabled (keeps step numbering stable, and they pass the
    averaged spectrum through untouched).
    """
    g = _last_group_index(pipeline)
    steps = []
    for i, s in enumerate(pipeline.steps):
        if s.enabled and s.name in _COHORT_NAMES:
            continue
        c = s.model_copy(deep=True)
        if g is not None and i < g:
            c = c.model_copy(update={"enabled": False})
        steps.append(c)
    return _with_steps(pipeline, steps)


def _prefix_pipeline_before_index(pipeline: Pipeline, idx: int) -> Pipeline:
    """
    Steps that transform the cohort's current spectra before ``idx``.

    Starts after the last group_average before ``idx`` (earlier steps are baked into the averages)
    and excludes cohort steps (they don't transform XY).
    """
    g = _last_group_index(pipeline, before=idx)
    start = 0 if g is None else g + 1
    steps = []
    for s in pipeline.steps[start:idx]:
        if s.enabled and s.name in _COHORT_NAMES:
            continue
        steps.append(s.model_copy(deep=True))
    return _with_steps(pipeline, steps)


def _expand_to_touched_groups(
    *, dataset: DatasetRecord, step: PipelineStep, refs: list[Any], universe: list[Any]
) -> tuple[list[Any], list[Any]]:
    """
    Plan the groups of ``step`` over ``universe`` (labels only) and return (refs to process, touched plan).

    The refs to process are the given ``refs`` plus every other member of a group they belong to, so each
    aggregate is complete. The plan holds only those touched groups.
    """
    from sersflow.api.services.spectrum_context import load_spectrum_contexts
    from sersflow.core.preprocess.group_average import GroupAverageParams, plan_groups

    gparams = GroupAverageParams.from_dict(step.params)
    ctxs = load_spectrum_contexts(universe)
    plan = plan_groups([(c.spectrum_id, c.labels) for c in ctxs], gparams, dataset_id=dataset.dataset_id)
    subset_ids = {str(r.spectrum_id) for r in refs}
    touched = [g for g in plan if subset_ids.intersection(g.member_ids)]
    needed = {sid for g in touched for sid in g.member_ids}
    expanded = [r for r in universe if str(r.spectrum_id) in needed]
    return expanded, touched


def _validate_group_references(pipeline: Pipeline, group_idx: int) -> None:
    """Steps after a group step cannot point back at steps before it (those no longer run per spectrum)."""
    before_ids = {s.step_id for s in pipeline.steps[:group_idx] if s.step_id}
    for s in pipeline.steps[group_idx + 1 :]:
        if not s.enabled:
            continue
        refs = {s.after_step_id, (s.params or {}).get("baseline_step_id")}
        hit = sorted(str(r) for r in refs if r and r in before_ids)
        if hit:
            raise ValueError(
                f"Step {s.name!r} after group_average references a step before it ({', '.join(hit)}). "
                "Move the group_average step or the referenced step."
            )


def _finite_score(v: float) -> bool:
    return bool(np.isfinite(float(v)))


def apply_pipeline_qc_filters(
    *,
    dataset: DatasetRecord,
    pipeline: Pipeline,
    refs: list[Any],
    cache_namespace: str,
    strict: bool = True,
    group_universe: list[Any] | None = None,
) -> tuple[list[Any], list[QcResult]]:
    """
    Apply session cohort QC steps (low_signal / outlier) in pipeline order.

    ``group_universe`` (the whole cohort the first group_average step would see, e.g. every dataset spectrum)
    makes a subset preview aggregate *complete* groups: groups are planned over the universe from labels,
    the members of every group touched by ``refs`` are loaded too, and only those groups are returned.

    metadata_filter is not applied here: it runs in the XY engine as a branch-local mask
    (respects input_from), emptying non-matching spectra on that branch.
    """
    cfg = EngineConfig(cache_namespace=cache_namespace)
    active_refs = list(refs)
    reports: list[QcResult] = []

    first_group = next(
        (i for i, s in enumerate(pipeline.steps) if s.enabled and s.name == GROUP_STEP_NAME), None
    )
    universe_plan = None
    if group_universe is not None and first_group is not None:
        active_refs, universe_plan = _expand_to_touched_groups(
            dataset=dataset, step=pipeline.steps[first_group], refs=active_refs, universe=group_universe
        )

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

        if step.name == GROUP_STEP_NAME:
            from sersflow.api.services.group_average import average_refs
            from sersflow.core.preprocess.group_average import GroupAverageParams

            _validate_group_references(pipeline, idx)
            gparams = GroupAverageParams.from_dict(step.params)
            derived, gwarnings = average_refs(
                dataset_id=dataset.dataset_id,
                refs=active_refs,
                finals=finals,
                params=gparams,
                planned=universe_plan if idx == first_group else None,
            )
            members_by_id = {d.spectrum_id: list(d.member_spectrum_ids) for d in derived}
            active_refs = list(derived)
            reports.append(
                QcResult(
                    step_id=(step.step_id or None),
                    step_index=idx,
                    step_name=step.name,
                    excluded_spectrum_ids=[],
                    scores_by_spectrum_id={},
                    meta={
                        "n_groups": len(derived),
                        "members_by_group": members_by_id,
                        "warnings": gwarnings,
                        "rule": gparams.rule_dict(),
                    },
                )
            )
            continue

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
    clipped = _with_steps(
        pipeline,
        [s.model_copy(deep=True) for s in pipeline.steps[: max(0, int(stop_before_step_index))]],
    )
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
