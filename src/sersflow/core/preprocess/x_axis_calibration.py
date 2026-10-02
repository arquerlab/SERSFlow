"""X-axis calibration: fixed offset, single reference band, or grouped reference band."""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from sersflow.core.metrics.fitting_features import (
    _feature_keys_for_component,
    _param_keys_for_component,
)
from sersflow.core.preprocess.fitting import FitResult, fit_curve, fit_problem_from_step_params
from sersflow.core.qc.metadata_filter import evaluate_filters
from sersflow.core.spectrum import XY

logger = logging.getLogger(__name__)

# Feature-export prefixes (s{N}_) when multiple fittings exist; calibration keys are step-local.
_LEGACY_MULTI_FIT_POS_PREFIX = re.compile(r"^s\d+_(?=fit_)")

COHORT_CALIBRATION_METHODS = frozenset(
    {
        "single_reference_band",
        "grouped_reference_band",
        # Legacy id accepted as alias of single_reference_band (cohort / average).
        "reference_peak",
    }
)


def canonicalize_calibration_pos_key(pos_key: str) -> str:
    """Strip optional ``s{N}_`` feature-export prefix; calibration keys are step-local."""
    return _LEGACY_MULTI_FIT_POS_PREFIX.sub("", str(pos_key or "").strip())


def normalize_region_token(name: str | None) -> str:
    """Lowercase region label with spaces/underscores removed (``O 1s`` → ``o1s``)."""
    return re.sub(r"[\s_]+", "", str(name or "").strip().lower())


def is_valence_band_region_name(name: str | None) -> bool:
    """True when a region label looks like valence-band / Fermi-edge / VB."""
    s = str(name or "").strip().lower()
    if not s:
        return False
    return "valence" in s or "fermi" in s or "vb" in s


def regions_match(a: str | None, b: str | None) -> bool:
    """Case/space/underscore-insensitive region equality."""
    ta = normalize_region_token(a)
    tb = normalize_region_token(b)
    return bool(ta) and ta == tb


def is_valence_partner_for_region(vb_region: str | None, core_region: str | None) -> bool:
    """
    Valence partner for core region R: VB/fermi/valence marker AND contains normalized R token.

    Example: core ``O 1s`` pairs with ``vb-O1s``, ``VB O1s``, ``fermi_O1s``.
    """
    if not is_valence_band_region_name(vb_region):
        return False
    token = normalize_region_token(core_region)
    if not token:
        return False
    vb_norm = normalize_region_token(vb_region)
    return token in vb_norm


def resolve_calibration_target_x(
    *,
    method: str,
    params: Mapping[str, Any],
    fitting_xps_region: str | None,
    spectrum_xps_region: str | None = None,
) -> float:
    """Valence/Fermi references use target 0 eV; otherwise user ``target_x``."""
    del method  # reserved for future method-specific defaults
    region = fitting_xps_region or spectrum_xps_region
    if is_valence_band_region_name(region):
        return 0.0
    if "target_x" not in params:
        raise ValueError("target_x must be provided for x_axis_calibration reference methods")
    target = float(params["target_x"])
    if not math.isfinite(target):
        raise ValueError("target_x must be finite for x_axis_calibration")
    return target


def fitting_pos_keys_for_step(
    step_params: dict[str, Any],
    *,
    step_index: int = 0,
    multi_fitting: bool = False,
) -> list[str]:
    """Return peak-position feature keys for a fitting step (``*_pos`` and Fermi ``*_center``)."""
    region = step_params.get("xps_region")
    xps_region = str(region).strip() if region is not None and str(region).strip() else None
    comps = step_params.get("components")
    if not isinstance(comps, list):
        return []
    out: list[str] = []
    for row in comps:
        if not isinstance(row, dict):
            continue
        ctype = str(row.get("component_type", "")).strip()
        cid = str(row.get("component_id") or "").strip() or "comp"
        try:
            param_keys = _param_keys_for_component(row)
        except ValueError:
            continue
        for key in _feature_keys_for_component(
            step_index, multi_fitting, cid, ctype, param_keys, xps_region=xps_region
        ):
            if key.endswith("_pos") or key.endswith("_center"):
                out.append(key)
    return out


def calibration_pos_keys_for_step(step_params: dict[str, Any]) -> list[str]:
    """Position keys offered/accepted by ``x_axis_calibration`` (never ``s{N}_``-prefixed)."""
    return fitting_pos_keys_for_step(step_params, step_index=0, multi_fitting=False)


def _pos_values_from_fit_result(
    res: FitResult,
    step_params: dict[str, Any],
    *,
    step_index: int,
    multi_fitting: bool,
) -> dict[str, float]:
    region = step_params.get("xps_region")
    xps_region = str(region).strip() if region is not None and str(region).strip() else None
    comps = step_params.get("components")
    if not isinstance(comps, list):
        return {}
    values: dict[str, float] = {}
    for m, row in zip(res.mapping, comps):
        if not isinstance(row, dict):
            continue
        ctype = str(row.get("component_type", "")).strip()
        cid = str(row.get("component_id") or "").strip() or "comp"
        try:
            param_keys = _param_keys_for_component(row)
        except ValueError:
            continue
        keys = _feature_keys_for_component(
            step_index, multi_fitting, cid, ctype, param_keys, xps_region=xps_region
        )
        keys_list = list(m.get("param_keys") or [])
        start, end = m.get("index_range", [0, 0])
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        sl = res.p_opt[start:end]
        pk = {keys_list[j]: float(sl[j]) for j in range(min(len(keys_list), len(sl)))}
        for param_key, final_key in zip(keys_list, keys[: len(keys_list)]):
            if not (final_key.endswith("_pos") or final_key.endswith("_center")):
                continue
            value = pk.get(param_key)
            if value is not None and math.isfinite(value):
                values[final_key] = float(value)
    return values


def measured_pos_from_fitting_xy(
    xy: XY,
    fit_params: dict[str, Any],
    *,
    step_index: int = 0,
    multi_fitting: bool = False,
    pos_key: str,
    technique_family: str | None = None,
) -> float:
    """
    Re-fit ``xy`` with ``fit_params`` and return the value for ``pos_key`` (or Fermi ``*_center``).

    Raises ValueError when the fit fails or ``pos_key`` is missing / non-finite.
    """
    del step_index, multi_fitting  # naming is always step-local for calibration
    key = canonicalize_calibration_pos_key(pos_key)
    if not key:
        raise ValueError("pos_key must be provided for x_axis_calibration reference methods")
    expected = calibration_pos_keys_for_step(fit_params)
    if key not in expected:
        raise ValueError(
            f"pos_key {key!r} is not a position feature of the selected fitting step "
            f"(expected one of {expected})"
        )
    if xy.x.size == 0 or xy.y.size == 0:
        raise ValueError("x_axis_calibration: fitting input spectrum is empty")

    params = dict(fit_params)
    if technique_family and "technique_family" not in params:
        params["technique_family"] = technique_family
    try:
        prob = fit_problem_from_step_params(xy, params)
    except ValueError as e:
        raise ValueError(f"x_axis_calibration: cannot build fit problem: {e}") from e
    if prob is None:
        raise ValueError("x_axis_calibration: fitting step has no components")
    try:
        res = fit_curve(prob)
    except (ValueError, RuntimeError) as e:
        raise ValueError(f"x_axis_calibration: fit failed: {e}") from e

    values = _pos_values_from_fit_result(res, fit_params, step_index=0, multi_fitting=False)
    measured = values.get(key)
    if measured is None or not math.isfinite(measured):
        raise ValueError(f"x_axis_calibration: fitted {key!r} is missing or non-finite")
    return float(measured)


def calibration_method_needs_cohort(method: str | None) -> bool:
    m = str(method or "fixed_offset").strip().lower()
    return m in COHORT_CALIBRATION_METHODS


def pipeline_needs_calibration_cohort(steps: Sequence[Any]) -> bool:
    for step in steps:
        if isinstance(step, dict):
            enabled = step.get("enabled", True)
            name = str(step.get("name") or "")
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
        else:
            enabled = getattr(step, "enabled", True)
            name = str(getattr(step, "name", "") or "")
            raw = getattr(step, "params", None)
            params = dict(raw) if isinstance(raw, dict) else {}
        if enabled is False:
            continue
        if name.strip() != "x_axis_calibration":
            continue
        if calibration_method_needs_cohort(str(params.get("method") or "")):
            return True
    return False


def calibration_delta(params: dict[str, Any]) -> float:
    """Return the additive x shift from calibration params (including runtime ``_delta``)."""
    method = str(params.get("method", "fixed_offset")).strip().lower()
    if method == "fixed_offset":
        if "offset" not in params:
            raise ValueError("offset must be provided for x_axis_calibration method='fixed_offset'")
        offset = float(params["offset"])
        if not math.isfinite(offset):
            raise ValueError("offset must be finite for x_axis_calibration method='fixed_offset'")
        return offset

    if method in COHORT_CALIBRATION_METHODS:
        if "_delta" in params:
            delta = float(params["_delta"])
            if not math.isfinite(delta):
                raise ValueError("x_axis_calibration _delta must be finite")
            return delta
        # Legacy per-spectrum path (single-spectrum engine without cohort precompute).
        if "_measured_pos" in params:
            measured = float(params["_measured_pos"])
            if not math.isfinite(measured):
                raise ValueError("_measured_pos must be finite for x_axis_calibration")
            target = resolve_calibration_target_x(
                method=method,
                params=params,
                fitting_xps_region=str(params.get("_fitting_xps_region") or "") or None,
                spectrum_xps_region=str(params.get("_spectrum_xps_region") or "") or None,
            )
            return target - measured
        raise ValueError(
            f"x_axis_calibration method={method!r} requires cohort precompute (_delta) "
            "or legacy _measured_pos"
        )

    raise ValueError(
        f"Unknown x_axis_calibration method {method!r} "
        "(expected 'fixed_offset', 'single_reference_band', or 'grouped_reference_band')"
    )


def apply_x_axis_calibration(xy: XY, params: dict[str, Any]) -> XY:
    x = np.asarray(xy.x, dtype=float).ravel()
    y = np.asarray(xy.y, dtype=float).ravel()
    if x.size == 0 or y.size == 0:
        return xy
    if x.size != y.size:
        raise ValueError("x_axis_calibration: x and y must have the same length")
    delta = calibration_delta(params)
    if delta == 0.0:
        return XY(x=xy.x, y=xy.y)
    return XY(x=x + delta, y=y.astype(float, copy=False))


@dataclass
class CalibrationCohortResult:
    """Per-spectrum deltas for one calibration step, plus human-readable warnings."""

    deltas: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


MeasureFn = Callable[[str, dict[str, Any], str], float]
# (spectrum_id, fit_params, pos_key) -> measured position


def _step_enabled(step: Any) -> bool:
    if isinstance(step, dict):
        return step.get("enabled", True) is not False
    return getattr(step, "enabled", True) is not False


def _step_name(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("name") or "").strip()
    return str(getattr(step, "name", "") or "").strip()


def _step_id(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("step_id") or step.get("id") or "").strip()
    return str(getattr(step, "step_id", None) or getattr(step, "id", "") or "").strip()


def _step_params(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        raw = step.get("params")
        return dict(raw) if isinstance(raw, dict) else {}
    raw = getattr(step, "params", None)
    return dict(raw) if isinstance(raw, dict) else {}


def find_calibration_steps(steps: Sequence[Any]) -> list[tuple[int, Any, dict[str, Any]]]:
    out: list[tuple[int, Any, dict[str, Any]]] = []
    for i, step in enumerate(steps):
        if not _step_enabled(step):
            continue
        if _step_name(step) != "x_axis_calibration":
            continue
        params = _step_params(step)
        method = str(params.get("method") or "fixed_offset").strip().lower()
        if calibration_method_needs_cohort(method):
            out.append((i, step, params))
    return out


def _find_fitting_step(steps: Sequence[Any], fitting_step_id: str, *, before_index: int) -> Any:
    fid = str(fitting_step_id or "").strip()
    if not fid:
        raise ValueError("fitting_step_id must be provided for x_axis_calibration reference methods")
    for i, step in enumerate(steps):
        if i >= before_index:
            break
        if not _step_enabled(step):
            continue
        if _step_name(step) != "fitting":
            continue
        if _step_id(step) == fid:
            return step
    raise ValueError(f"fitting_step_id {fid!r} must refer to an earlier enabled fitting step")


def _spectrum_region(labels: Mapping[str, Any] | None) -> str:
    if not isinstance(labels, Mapping):
        return ""
    return str(labels.get("xps_region") or "").strip()


def compute_calibration_deltas_for_step(
    *,
    spectrum_ids: Sequence[str],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    cal_params: Mapping[str, Any],
    fit_params: Mapping[str, Any],
    measure: MeasureFn,
    technique_family: str | None = None,
) -> CalibrationCohortResult:
    """
    Compute per-spectrum x deltas for one calibration step.

    ``measure(spectrum_id, fit_params, pos_key)`` must re-fit that spectrum's fitting input.
    """
    del technique_family  # fit_params already carry technique when needed
    method = str(cal_params.get("method") or "").strip().lower()
    if method == "reference_peak":
        method = "single_reference_band"

    pos_key = canonicalize_calibration_pos_key(str(cal_params.get("pos_key") or ""))
    fit_p = dict(fit_params)
    fit_region = str(fit_p.get("xps_region") or "").strip() or None

    result = CalibrationCohortResult()
    ids = [str(s) for s in spectrum_ids]

    if method == "single_reference_band":
        filters = cal_params.get("reference_filters")
        filter_list = [dict(x) for x in filters] if isinstance(filters, list) else []
        ref_ids = [
            sid for sid in ids if evaluate_filters(labels_by_id.get(sid) or {}, filter_list)
        ]
        if not ref_ids:
            result.warnings.append(
                "single_reference_band: no spectra matched reference_filters; no shift applied"
            )
            for sid in ids:
                result.deltas[sid] = 0.0
            return result

        measured: list[float] = []
        for sid in ref_ids:
            try:
                measured.append(measure(sid, fit_p, pos_key))
            except (ValueError, RuntimeError) as e:
                result.warnings.append(f"single_reference_band: measure failed for {sid}: {e}")
        if not measured:
            result.warnings.append("single_reference_band: all reference measurements failed")
            for sid in ids:
                result.deltas[sid] = 0.0
            return result

        mean_pos = float(sum(measured) / len(measured))
        ref_region = fit_region or _spectrum_region(labels_by_id.get(ref_ids[0]))
        target = resolve_calibration_target_x(
            method=method,
            params=cal_params,
            fitting_xps_region=ref_region,
        )
        delta = target - mean_pos
        if len(measured) > 1:
            result.warnings.append(
                f"single_reference_band: averaging {len(measured)} reference measurement(s)"
            )
        for sid in ids:
            result.deltas[sid] = delta
        return result

    if method == "grouped_reference_band":
        group_by = str(cal_params.get("group_by") or "").strip()
        if not group_by:
            raise ValueError("group_by must be provided for grouped_reference_band")
        ref_mode = str(cal_params.get("reference_mode") or "core_level").strip().lower()
        if ref_mode not in ("core_level", "valence_band"):
            raise ValueError("reference_mode must be 'core_level' or 'valence_band'")

        groups: dict[str, list[str]] = defaultdict(list)
        for sid in ids:
            labels = labels_by_id.get(sid) or {}
            raw = labels.get(group_by)
            gkey = str(raw) if raw is not None else ""
            groups[gkey].append(sid)

        if ref_mode == "core_level":
            ref_region = str(cal_params.get("reference_region") or fit_region or "").strip()
            if not ref_region:
                raise ValueError(
                    "reference_region or fitting xps_region required for grouped core_level"
                )
            missing_groups: list[str] = []
            for gkey, members in groups.items():
                ref_sid = next(
                    (
                        sid
                        for sid in members
                        if regions_match(_spectrum_region(labels_by_id.get(sid)), ref_region)
                    ),
                    None,
                )
                if ref_sid is None:
                    missing_groups.append(gkey or "(empty)")
                    for sid in members:
                        result.deltas[sid] = 0.0
                    continue
                try:
                    measured_v = measure(ref_sid, fit_p, pos_key)
                except (ValueError, RuntimeError) as e:
                    result.warnings.append(
                        f"grouped_reference_band: measure failed for group {gkey!r} ({ref_sid}): {e}"
                    )
                    for sid in members:
                        result.deltas[sid] = 0.0
                    continue
                target = resolve_calibration_target_x(
                    method=method,
                    params=cal_params,
                    fitting_xps_region=ref_region,
                    spectrum_xps_region=_spectrum_region(labels_by_id.get(ref_sid)),
                )
                delta = target - measured_v
                for sid in members:
                    result.deltas[sid] = delta
            if missing_groups:
                result.warnings.append(
                    "grouped_reference_band (core_level): missing "
                    f"{ref_region!r} in groups: {', '.join(missing_groups)}"
                )
            return result

        # valence_band: per core region R in group, use paired VB Fermi (target 0).
        unpaired: list[str] = []
        for gkey, members in groups.items():
            vb_cache: dict[str, float] = {}
            for sid in members:
                region = _spectrum_region(labels_by_id.get(sid))
                if is_valence_band_region_name(region):
                    try:
                        if sid not in vb_cache:
                            vb_cache[sid] = measure(sid, fit_p, pos_key)
                        result.deltas[sid] = 0.0 - vb_cache[sid]
                    except (ValueError, RuntimeError) as e:
                        result.warnings.append(
                            f"grouped_reference_band: VB measure failed for {sid}: {e}"
                        )
                        result.deltas[sid] = 0.0
                    continue

                partner = next(
                    (
                        vid
                        for vid in members
                        if is_valence_partner_for_region(
                            _spectrum_region(labels_by_id.get(vid)), region
                        )
                    ),
                    None,
                )
                if partner is None:
                    unpaired.append(f"{gkey or '(empty)'}:{region or '?'}")
                    result.deltas[sid] = 0.0
                    continue
                try:
                    if partner not in vb_cache:
                        vb_cache[partner] = measure(partner, fit_p, pos_key)
                    result.deltas[sid] = 0.0 - vb_cache[partner]
                except (ValueError, RuntimeError) as e:
                    result.warnings.append(
                        f"grouped_reference_band: VB measure failed for {partner}: {e}"
                    )
                    result.deltas[sid] = 0.0
            for sid in members:
                result.deltas.setdefault(sid, 0.0)
        if unpaired:
            result.warnings.append(
                "grouped_reference_band (valence_band): no VB partner for: " + ", ".join(unpaired)
            )
        return result

    raise ValueError(f"Unsupported cohort calibration method {method!r}")


def compute_all_calibration_deltas(
    *,
    steps: Sequence[Any],
    spectrum_ids: Sequence[str],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    measure_for_fitting_step: Callable[[str, str, dict[str, Any], str], float],
    technique_family: str | None = None,
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """
    For each cohort calibration step, return deltas keyed by step_id then spectrum_id.

    ``measure_for_fitting_step(spectrum_id, fitting_step_id, fit_params, pos_key)``.
    """
    by_step: dict[str, dict[str, float]] = {}
    warnings: list[str] = []
    for cal_index, step, cal_params in find_calibration_steps(steps):
        sid_key = _step_id(step) or f"cal@{cal_index}"
        fitting_step_id = str(cal_params.get("fitting_step_id") or "").strip()
        fit_step = _find_fitting_step(steps, fitting_step_id, before_index=cal_index)
        fit_params = _step_params(fit_step)
        if technique_family and "technique_family" not in fit_params:
            fit_params = {**fit_params, "technique_family": technique_family}

        def _measure(
            spectrum_id: str,
            fp: dict[str, Any],
            pos_key: str,
            _fsid: str = fitting_step_id,
        ) -> float:
            return measure_for_fitting_step(spectrum_id, _fsid, fp, pos_key)

        try:
            one = compute_calibration_deltas_for_step(
                spectrum_ids=spectrum_ids,
                labels_by_id=labels_by_id,
                cal_params=cal_params,
                fit_params=fit_params,
                measure=_measure,
                technique_family=technique_family,
            )
        except ValueError as e:
            warnings.append(str(e))
            by_step[sid_key] = {str(s): 0.0 for s in spectrum_ids}
            continue
        by_step[sid_key] = one.deltas
        warnings.extend(one.warnings)
    return by_step, warnings
