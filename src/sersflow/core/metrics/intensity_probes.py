from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from sersflow.core.metrics.key_dedupe import dedupe_parallel
from sersflow.core.metrics.peaks import nearest_peak_to_target
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.spectrum import XY

Acquisition = Literal["fixed", "nearest_peak"]
Extrapolation = Literal["nan", "clip"]
InterpMethod = Literal["nearest", "linear_interp"]
ProbeSource = Literal["signal", "baseline"]


@dataclass(frozen=True)
class ProbeSpec:
    id: str
    target_cm1: float
    acquisition: Acquisition
    method: InterpMethod
    extrapolation: Extrapolation
    window_cm1: float | None
    peak_find: dict[str, Any]
    no_peak_fallback: Literal["none", "fixed_nearest"]
    source: ProbeSource
    baseline_step_id: str | None


def _safe_id_fragment(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip())
    return t or "probe"


def default_probe_id(target_cm1: float, index: int) -> str:
    s = f"{float(target_cm1):g}".replace(".", "d").replace("-", "m")
    return f"cm1_{s}_{index}"


def intensity_feature_key(probe_id: str, *, kind: Literal["I", "peak_pos"]) -> str:
    pid = _safe_id_fragment(probe_id)
    if kind == "I":
        return f"I_{pid}"
    return f"peak_pos_cm1_{pid}"


def parse_probes(params: dict[str, Any]) -> list[ProbeSpec]:
    raw = params.get("probes")
    if not isinstance(raw, list) or not raw:
        raise ValueError("spectral_intensities requires params.probes as a non-empty list")
    out: list[ProbeSpec] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"spectral_intensities.probes[{i}] must be an object")
        target = row.get("target_cm1")
        if target is None:
            raise ValueError(f"spectral_intensities.probes[{i}] requires target_cm1")
        tid = str(row.get("id") or "").strip()
        if not tid:
            tid = default_probe_id(float(target), i)
        acq = str(row.get("acquisition", "fixed")).strip().lower()
        if acq not in ("fixed", "nearest_peak"):
            raise ValueError(f"spectral_intensities.probes[{i}].acquisition must be fixed or nearest_peak")
        method = str(row.get("method", "linear_interp")).strip().lower()
        if method not in ("nearest", "linear_interp"):
            raise ValueError(f"spectral_intensities.probes[{i}].method must be nearest or linear_interp")
        ext = str(row.get("extrapolation", "nan")).strip().lower()
        if ext not in ("nan", "clip"):
            raise ValueError(f"spectral_intensities.probes[{i}].extrapolation must be nan or clip")
        w = row.get("window_cm1")
        window = float(w) if w is not None else None
        pf = row.get("peak_find")
        peak_find = dict(pf) if isinstance(pf, dict) else {}
        fb = str(row.get("no_peak_fallback", "none")).strip().lower()
        if fb not in ("none", "fixed_nearest"):
            raise ValueError(f"spectral_intensities.probes[{i}].no_peak_fallback must be none or fixed_nearest")
        src = str(row.get("source", "signal")).strip().lower()
        if src not in ("signal", "baseline"):
            raise ValueError(f"spectral_intensities.probes[{i}].source must be signal or baseline")
        baseline_step_id = str(row.get("baseline_step_id") or "").strip() or None
        if src == "baseline" and not baseline_step_id:
            raise ValueError(f"spectral_intensities.probes[{i}].baseline_step_id is required when source is baseline")
        out.append(
            ProbeSpec(
                id=tid,
                target_cm1=float(target),
                acquisition=acq,  # type: ignore[arg-type]
                method=method,  # type: ignore[arg-type]
                extrapolation=ext,  # type: ignore[arg-type]
                window_cm1=window,
                peak_find=peak_find,
                no_peak_fallback=fb,  # type: ignore[arg-type]
                source=src,  # type: ignore[arg-type]
                baseline_step_id=baseline_step_id,
            )
        )
    return out


def _step_enabled(step: Any) -> bool:
    if isinstance(step, dict):
        return bool(step.get("enabled", True))
    return bool(getattr(step, "enabled", True))


def _step_name(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("name", ""))
    return str(getattr(step, "name", ""))


def _step_id(step: Any) -> str | None:
    if isinstance(step, dict):
        sid = step.get("step_id")
    else:
        sid = getattr(step, "step_id", None)
    text = str(sid or "").strip()
    return text or None


def _step_params(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        params = step.get("params")
    else:
        params = getattr(step, "params", None)
    return dict(params) if isinstance(params, dict) else {}


def _baseline_step_index(
    pipeline: Any,
    baseline_step_id: str,
    *,
    before_index: int | None = None,
) -> int:
    steps = getattr(pipeline, "steps", None) or []
    for i, step in enumerate(steps):
        if _step_id(step) != baseline_step_id:
            continue
        if not _step_enabled(step):
            raise ValueError("baseline_step_id must refer to an enabled baseline step")
        if _step_name(step) != "baseline":
            raise ValueError("baseline_step_id must refer to a baseline step")
        if before_index is not None and i >= before_index:
            raise ValueError("baseline_step_id must refer to an earlier pipeline step")
        return i
    raise ValueError(f"baseline_step_id {baseline_step_id!r} does not match any pipeline step")


def resolve_baseline_curve_xy(
    pipeline: Any,
    baseline_step_id: str,
    *,
    per_step_input_xy: dict[int, XY],
    before_index: int | None = None,
) -> XY:
    """
    Reconstruct the baseline curve for a baseline step: input_y - output_y.

    Uses per-step input captured during pipeline execution and re-applies the baseline transform.
    """
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    k = _baseline_step_index(pipeline, baseline_step_id, before_index=before_index)
    baseline_step = steps[k]
    sn = sns[k]
    baseline_input = per_step_input_xy.get(sn)
    if baseline_input is None:
        raise ValueError("selected baseline step has no available input/output")
    from sersflow.core.pipeline.steps import DEFAULT_STEPS

    impl = DEFAULT_STEPS.get("baseline")
    if impl is None:
        raise ValueError("baseline step implementation is unavailable")
    baseline_output = impl.transform(baseline_input, _step_params(baseline_step))
    if (
        baseline_input.x.size != baseline_output.x.size
        or baseline_input.y.size != baseline_output.y.size
        or baseline_input.x.size != baseline_input.y.size
    ):
        raise ValueError("selected baseline step input/output arrays are incompatible")
    baseline_y = baseline_input.y.astype(float, copy=False) - baseline_output.y.astype(float, copy=False)
    return XY(x=baseline_input.x, y=baseline_y)


def _resolve_baseline_curves_for_probes(
    pipeline: Any,
    probes: list[ProbeSpec],
    *,
    per_step_input_xy: dict[int, XY] | None,
    before_index: int,
) -> dict[str, XY]:
    if per_step_input_xy is None:
        raise ValueError("per_step_input_xy is required for baseline probes")
    needed = {p.baseline_step_id for p in probes if p.source == "baseline" and p.baseline_step_id}
    curves: dict[str, XY] = {}
    for bid in needed:
        if bid is None:
            continue
        if bid not in curves:
            curves[bid] = resolve_baseline_curve_xy(
                pipeline,
                bid,
                per_step_input_xy=per_step_input_xy,
                before_index=before_index,
            )
    return curves


def _sort_xy(xy: XY) -> tuple[np.ndarray, np.ndarray]:
    x = xy.x.astype(float, copy=False)
    y = xy.y.astype(float, copy=False)
    if x.size <= 1:
        return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    order = np.argsort(x)
    return np.asarray(x[order], dtype=float), np.asarray(y[order], dtype=float)


def _fixed_intensity(
    xs: np.ndarray,
    ys: np.ndarray,
    target_cm1: float,
    method: InterpMethod,
    extrapolation: Extrapolation,
) -> float | None:
    if xs.size == 0:
        return None
    t = float(target_cm1)
    if method == "nearest":
        i = int(np.argmin(np.abs(xs - t)))
        return float(ys[i])
    # linear_interp
    left = np.nan if extrapolation == "nan" else float(ys[0])
    right = np.nan if extrapolation == "nan" else float(ys[-1])
    return float(np.interp(t, xs, ys, left=left, right=right))


def _probe_xy(
    p: ProbeSpec,
    xy_signal: XY,
    *,
    baseline_curves: dict[str, XY] | None,
) -> XY:
    if p.source == "baseline":
        if not p.baseline_step_id:
            raise ValueError(f"probe {p.id!r} requires baseline_step_id when source is baseline")
        if baseline_curves is None or p.baseline_step_id not in baseline_curves:
            raise ValueError(f"baseline curve for step {p.baseline_step_id!r} is unavailable")
        return baseline_curves[p.baseline_step_id]
    return xy_signal


def _evaluate_probe(p: ProbeSpec, xy: XY) -> dict[str, float | None]:
    xs, ys = _sort_xy(xy)
    out: dict[str, float | None] = {}
    ikey = intensity_feature_key(p.id, kind="I")
    if p.acquisition == "fixed":
        out[ikey] = _fixed_intensity(xs, ys, p.target_cm1, p.method, p.extrapolation)
        return out

    intensity, pos = nearest_peak_to_target(
        xy,
        target_cm1=p.target_cm1,
        window_cm1=p.window_cm1,
        peak_find=p.peak_find,
    )
    pk = intensity_feature_key(p.id, kind="peak_pos")
    if intensity is None and p.no_peak_fallback == "fixed_nearest":
        intensity = _fixed_intensity(xs, ys, p.target_cm1, "nearest", p.extrapolation)
    if pos is None:
        pos = float(p.target_cm1)
    out[pk] = pos
    out[ikey] = intensity
    return out


def evaluate_spectral_intensity_probes(
    xy: XY,
    params: dict[str, Any],
    *,
    baseline_curves: dict[str, XY] | None = None,
) -> dict[str, float | None]:
    probes = parse_probes(params)
    out: dict[str, float | None] = {}
    for p in probes:
        xy_use = _probe_xy(p, xy, baseline_curves=baseline_curves)
        out.update(_evaluate_probe(p, xy_use))
    return out


def feature_keys_for_probes(params: dict[str, Any]) -> list[str]:
    """Ordered feature column names for a spectral_intensities step (no XY required)."""
    probes = parse_probes(params)
    keys: list[str] = []
    for p in probes:
        keys.append(intensity_feature_key(p.id, kind="I"))
        if p.acquisition == "nearest_peak":
            keys.append(intensity_feature_key(p.id, kind="peak_pos"))
    return keys


def merge_spectral_intensity_step_features(
    pipeline_step_index: int,
    multi_spectral_steps: bool,
    features: dict[str, float | None],
) -> dict[str, float | None]:
    prefix = f"s{pipeline_step_index}_" if multi_spectral_steps else ""
    return {f"{prefix}{k}": v for k, v in features.items()}


def _raw_si_keys_and_nums(pipeline: Any) -> tuple[list[str], list[int]]:
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    si_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "spectral_intensities"]
    multi = len(si_indices) > 1
    raw: list[str] = []
    nums: list[int] = []
    for i in si_indices:
        step = steps[i]
        fk = feature_keys_for_probes(step.params)
        prefix = f"s{i}_" if multi else ""
        for k in fk:
            raw.append(f"{prefix}{k}")
            nums.append(sns[i])
    return raw, nums


def preview_feature_keys_for_pipeline(pipeline: Any) -> list[str]:
    """Column order for export manifest (no spectrum data required)."""
    raw, nums = _raw_si_keys_and_nums(pipeline)
    return dedupe_parallel(raw, nums)


def spectral_intensity_feature_key_groups_for_pipeline(pipeline: Any) -> dict[int, tuple[list[str], list[str]]]:
    """
    Map step_num -> (base_keys, final_keys) for enabled spectral_intensities steps.
    """
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw, nums = _raw_si_keys_and_nums(pipeline)
    final_keys = dedupe_parallel(raw, nums)
    si_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "spectral_intensities"]
    multi = len(si_indices) > 1
    out: dict[int, tuple[list[str], list[str]]] = {}
    key_cursor = 0
    for i in si_indices:
        step = steps[i]
        base_keys = feature_keys_for_probes(step.params)
        prefix = f"s{i}_" if multi else ""
        step_raw = [f"{prefix}{k}" for k in base_keys]
        final = final_keys[key_cursor : key_cursor + len(step_raw)]
        key_cursor += len(step_raw)
        out[sns[i]] = (base_keys, final)
    return out


def collect_spectral_intensity_features_for_pipeline(
    xy: XY,
    pipeline: Any,
    *,
    per_step_input_xy: dict[int, XY] | None = None,
) -> tuple[list[str], dict[str, float | None]]:
    """
    Evaluate all enabled spectral_intensities steps on the appropriate per-step input XY.

    When multiple spectral_intensities steps exist, prefix keys with s{pip_index}_ (legacy).
    """
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw, nums = _raw_si_keys_and_nums(pipeline)
    final_keys = dedupe_parallel(raw, nums)

    si_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "spectral_intensities"]
    multi = len(si_indices) > 1
    merged: dict[str, float | None] = {}
    ordered_keys: list[str] = []

    key_cursor = 0
    for i in si_indices:
        step = steps[i]
        base_keys = feature_keys_for_probes(step.params)
        prefix = f"s{i}_" if multi else ""
        step_raw = [f"{prefix}{k}" for k in base_keys]
        n = len(step_raw)
        step_final_keys = final_keys[key_cursor : key_cursor + n]
        key_cursor += n

        xy_use = per_step_input_xy.get(sns[i], xy) if per_step_input_xy is not None else xy
        probes = parse_probes(step.params)
        baseline_curves = _resolve_baseline_curves_for_probes(
            pipeline,
            probes,
            per_step_input_xy=per_step_input_xy,
            before_index=i,
        )
        raw_feats = evaluate_spectral_intensity_probes(
            xy_use,
            step.params,
            baseline_curves=baseline_curves or None,
        )
        for bk, fk in zip(base_keys, step_final_keys):
            merged[fk] = raw_feats.get(bk)
        ordered_keys.extend(step_final_keys)

    return ordered_keys, merged
