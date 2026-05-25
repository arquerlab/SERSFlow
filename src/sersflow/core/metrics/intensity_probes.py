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
            )
        )
    return out


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


def evaluate_spectral_intensity_probes(xy: XY, params: dict[str, Any]) -> dict[str, float | None]:
    probes = parse_probes(params)
    xs, ys = _sort_xy(xy)
    out: dict[str, float | None] = {}
    for p in probes:
        ikey = intensity_feature_key(p.id, kind="I")
        if p.acquisition == "fixed":
            out[ikey] = _fixed_intensity(xs, ys, p.target_cm1, p.method, p.extrapolation)
            continue

        intensity, pos = nearest_peak_to_target(
            xy,
            target_cm1=p.target_cm1,
            window_cm1=p.window_cm1,
            peak_find=p.peak_find,
        )
        pk = intensity_feature_key(p.id, kind="peak_pos")
        if intensity is None and p.no_peak_fallback == "fixed_nearest":
            intensity = _fixed_intensity(xs, ys, p.target_cm1, "nearest", p.extrapolation)
        # If no peak was detected, keep peak_pos numeric for downstream tools: use the probe target.
        if pos is None:
            pos = float(p.target_cm1)
        out[pk] = pos
        out[ikey] = intensity
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
        raw_feats = evaluate_spectral_intensity_probes(xy_use, step.params)
        for bk, fk in zip(base_keys, step_final_keys):
            merged[fk] = raw_feats.get(bk)
        ordered_keys.extend(step_final_keys)

    return ordered_keys, merged
