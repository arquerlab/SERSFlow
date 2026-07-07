from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from sersflow.core.metrics.key_dedupe import dedupe_parallel
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.spectrum import XY

IntegrationMode = Literal["signed", "positive", "absolute"]


@dataclass(frozen=True)
class IntegrationWindowSpec:
    id: str
    min_cm1: float
    max_cm1: float
    mode: IntegrationMode


def _safe_id_fragment(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip())
    return t or "area"


def default_window_id(index: int) -> str:
    return f"band{index + 1}"


def integration_feature_key(window_id: str) -> str:
    return f"area_{_safe_id_fragment(window_id)}"


def parse_integration_windows(params: dict[str, Any]) -> list[IntegrationWindowSpec]:
    raw = params.get("windows")
    if not isinstance(raw, list) or not raw:
        raise ValueError("spectral_integrations requires params.windows as a non-empty list")
    out: list[IntegrationWindowSpec] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"spectral_integrations.windows[{i}] must be an object")
        min_raw = row.get("min_cm1")
        max_raw = row.get("max_cm1")
        if min_raw is None or max_raw is None:
            raise ValueError(f"spectral_integrations.windows[{i}] requires min_cm1 and max_cm1")
        min_cm1 = float(min_raw)
        max_cm1 = float(max_raw)
        if not (np.isfinite(min_cm1) and np.isfinite(max_cm1)):
            raise ValueError(f"spectral_integrations.windows[{i}] min_cm1/max_cm1 must be finite")
        if max_cm1 <= min_cm1:
            raise ValueError(f"spectral_integrations.windows[{i}] max_cm1 must be greater than min_cm1")
        mode = str(row.get("mode", "signed")).strip().lower()
        if mode not in ("signed", "positive", "absolute"):
            raise ValueError(f"spectral_integrations.windows[{i}].mode must be signed, positive, or absolute")
        wid = str(row.get("id") or "").strip() or default_window_id(i)
        out.append(
            IntegrationWindowSpec(
                id=wid,
                min_cm1=min_cm1,
                max_cm1=max_cm1,
                mode=mode,  # type: ignore[arg-type]
            )
        )
    return out


def _sort_xy_unique(xy: XY) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(xy.x, dtype=float).ravel()
    y = np.asarray(xy.y, dtype=float).ravel()
    if x.size == 0 or y.size == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    if x.size != y.size:
        raise ValueError("spectral_integrations: x and y must have the same length")
    order = np.argsort(x)
    xs = x[order]
    ys = y[order]
    ux, inv = np.unique(xs, return_inverse=True)
    if ux.size == xs.size:
        return xs, ys
    sums = np.bincount(inv, weights=ys)
    counts = np.bincount(inv)
    return ux.astype(float), (sums / np.maximum(counts, 1)).astype(float)


def _window_samples(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    min_cm1: float,
    max_cm1: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    if xs.size < 2:
        return None
    lo = max(float(min_cm1), float(xs[0]))
    hi = min(float(max_cm1), float(xs[-1]))
    if hi <= lo:
        return None

    mask = (xs > lo) & (xs < hi)
    wx = np.concatenate(([lo], xs[mask], [hi])).astype(float)
    wy = np.interp(wx, xs, ys).astype(float)
    if wx.size < 2:
        return None
    return wx, wy


def integrate_window(xy: XY, spec: IntegrationWindowSpec) -> float | None:
    xs, ys = _sort_xy_unique(xy)
    samples = _window_samples(xs, ys, min_cm1=spec.min_cm1, max_cm1=spec.max_cm1)
    if samples is None:
        return None
    wx, wy = samples
    if spec.mode == "positive":
        wy = np.clip(wy, 0.0, None)
    elif spec.mode == "absolute":
        wy = np.abs(wy)
    return float(np.trapezoid(wy, wx))


def evaluate_spectral_integrations(xy: XY, params: dict[str, Any]) -> dict[str, float | None]:
    windows = parse_integration_windows(params)
    out: dict[str, float | None] = {}
    for w in windows:
        out[integration_feature_key(w.id)] = integrate_window(xy, w)
    return out


def feature_keys_for_windows(params: dict[str, Any]) -> list[str]:
    return [integration_feature_key(w.id) for w in parse_integration_windows(params)]


def _raw_integration_keys_and_nums(pipeline: Any) -> tuple[list[str], list[int]]:
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw: list[str] = []
    nums: list[int] = []
    integration_indices = [
        i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "spectral_integrations"
    ]
    multi = len(integration_indices) > 1
    for i in integration_indices:
        step = steps[i]
        prefix = f"s{i}_" if multi else ""
        for k in feature_keys_for_windows(step.params):
            raw.append(f"{prefix}{k}")
            nums.append(sns[i])
    return raw, nums


def preview_integration_feature_keys_for_pipeline(pipeline: Any) -> list[str]:
    raw, nums = _raw_integration_keys_and_nums(pipeline)
    return dedupe_parallel(raw, nums)


def integration_feature_key_groups_for_pipeline(pipeline: Any) -> dict[int, tuple[list[str], list[str]]]:
    """
    Map step_num -> (base_keys, final_keys) for enabled spectral_integrations steps.
    """
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw, nums = _raw_integration_keys_and_nums(pipeline)
    final_keys = dedupe_parallel(raw, nums)
    integration_indices = [
        i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "spectral_integrations"
    ]
    multi = len(integration_indices) > 1
    out: dict[int, tuple[list[str], list[str]]] = {}
    cursor = 0
    for i in integration_indices:
        step = steps[i]
        base_keys = feature_keys_for_windows(step.params)
        prefix = f"s{i}_" if multi else ""
        step_raw = [f"{prefix}{k}" for k in base_keys]
        final = final_keys[cursor : cursor + len(step_raw)]
        cursor += len(step_raw)
        out[sns[i]] = (base_keys, final)
    return out


def collect_integration_features_for_pipeline(
    xy: XY,
    pipeline: Any,
    *,
    per_step_input_xy: dict[int, XY] | None = None,
) -> tuple[list[str], dict[str, float | None]]:
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    groups = integration_feature_key_groups_for_pipeline(pipeline)
    ordered_keys = [k for _base, final in groups.values() for k in final]
    merged: dict[str, float | None] = {}
    for i, step in enumerate(steps):
        if not getattr(step, "enabled", True) or step.name != "spectral_integrations":
            continue
        sn = sns[i]
        base_keys, final_keys = groups.get(sn, ([], []))
        xy_use = per_step_input_xy.get(sn, xy) if per_step_input_xy is not None else xy
        raw_feats = evaluate_spectral_integrations(xy_use, step.params)
        for bk, fk in zip(base_keys, final_keys):
            merged[fk] = raw_feats.get(bk)
    return ordered_keys, merged
