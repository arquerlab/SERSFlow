"""IO1: acquisition statistics and auxiliary VAMAS arrays (transmission) for one dataset spectrum."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from sersflow.core.io.read_vms import block_meta_dict, count_statistics, read_vms_blocks
from sersflow.core.pipeline.engine import _resolve_ref_path
from sersflow.infra.datasets_store import DatasetRecord


def _finite_list(a: np.ndarray) -> list[float | None]:
    return [float(v) if np.isfinite(v) else None for v in np.asarray(a, dtype=float)]


def _text(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _geometry(ef: dict[str, Any]) -> dict[str, Any]:
    """ISO 14976 source / analyser axis angles (degrees from the sample normal) and the angle between them."""
    sp, sa = _num(ef.get("source_polar_angle")), _num(ef.get("source_azimuth"))
    ap, aa = _num(ef.get("analyser_axis_polar")), _num(ef.get("analyser_axis_azimuth"))
    angle = None
    if None not in (sp, sa, ap, aa) and not (sp == sa == ap == aa == 0.0):
        r = math.radians
        c = math.sin(r(sp)) * math.sin(r(ap)) * math.cos(r(sa) - r(aa)) + math.cos(r(sp)) * math.cos(r(ap))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, c))))
    return {
        "source_polar_deg": sp,
        "source_azimuth_deg": sa,
        "analyser_polar_deg": ap,
        "analyser_azimuth_deg": aa,
        "source_analyser_angle_deg": angle,
    }


def _max_channel(y: np.ndarray, stats: dict[str, Any]) -> dict[str, Any]:
    """Counts and count rate at the most intense channel (ISO 19830 asks for them)."""
    yf = np.asarray(y, dtype=float)
    if yf.size == 0 or not np.isfinite(yf).any():
        return {"y_max": None, "max_channel_counts": None, "max_channel_cps": None}
    ymax = float(np.nanmax(yf))
    scale = stats.get("counts_scale")
    counts = ymax * float(scale) if scale is not None else None
    dwell, scans = stats.get("dwell_time_s"), stats.get("n_scans")
    rate = counts / (float(dwell) * float(scans)) if counts is not None and dwell and scans else None
    return {"y_max": ymax, "max_channel_counts": counts, "max_channel_cps": rate}


def vamas_acquisition_payload(
    dataset: DatasetRecord,
    spectrum_id: str,
    *,
    include_arrays: bool = True,
) -> dict[str, Any]:
    """
    Read the spectrum's VAMAS block on demand (no re-import) and report what the ordinate is.

    Returns ``y_unit`` (counts | cps | unknown), dwell time, scans, ``counts_scale`` (counts per
    channel = y * counts_scale; None when y is not count-based), the corresponding variables, and
    (with ``include_arrays``) the binding-energy axis plus every auxiliary array such as
    ``transmission``. Raises KeyError / ValueError for unknown or non-VAMAS spectra.
    """
    ref = next((s for s in dataset.spectra if s.spectrum_id == spectrum_id), None)
    if ref is None:
        raise KeyError(f"spectrum not found in dataset: {spectrum_id}")
    if not str(ref.relative_path).lower().endswith(".vms"):
        raise ValueError("spectrum is not from a VAMAS (.vms) file")
    idx = ref.record_index
    blocks = read_vms_blocks(_resolve_ref_path(ref))[1]
    if idx is None or not (0 <= int(idx) < len(blocks)):
        raise ValueError(f"record_index {idx!r} out of range for {ref.relative_path}")
    block = blocks[int(idx)]
    meta = block_meta_dict(block)
    stats = count_statistics(meta)
    ef = block.extra_fields or {}
    out: dict[str, Any] = {
        "spectrum_id": spectrum_id,
        "relative_path": str(ref.relative_path),
        "record_index": int(idx),
        "block_name": block.block_name,
        "xps_region": meta.get("xps_region"),
        "y_unit": stats["y_unit"],
        "y_label": meta.get("y_label"),
        "signal_mode": ef.get("signal_mode"),
        "dwell_time_s": stats["dwell_time_s"],
        "n_scans": stats["n_scans"],
        "counts_scale": stats["counts_scale"],
        "pass_energy_eV": meta.get("pass_energy_eV"),
        "corresponding_variables": ef.get("corresponding_variables") or [],
        "aux_arrays": sorted(block.aux),
        "x_irregular": bool(ef.get("x_from_corresponding_variable")),
        "n_points": int(block.y.size),
        # R1 report: source, geometry and count statistics as recorded in the block.
        "technique": block.technique,
        "source_label": block.source_label,
        "excitation_energy_eV": block.excitation_energy_eV,
        "analyser_mode": _text(ef.get("analyser_mode")),
        "x_step_eV": abs(float(block.x_step)) if block.x_step is not None else None,
        **_geometry(ef),
        **_max_channel(block.y, stats),
    }
    if include_arrays:
        out["x"] = _finite_list(block.x)
        out["aux"] = {name: _finite_list(arr) for name, arr in sorted(block.aux.items())}
    return out
