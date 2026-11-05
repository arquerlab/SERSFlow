"""IO1: acquisition statistics and auxiliary VAMAS arrays (transmission) for one dataset spectrum."""

from __future__ import annotations

from typing import Any

import numpy as np

from sersflow.core.io.read_vms import block_meta_dict, count_statistics, read_vms_blocks
from sersflow.core.pipeline.engine import _resolve_ref_path
from sersflow.infra.datasets_store import DatasetRecord


def _finite_list(a: np.ndarray) -> list[float | None]:
    return [float(v) if np.isfinite(v) else None for v in np.asarray(a, dtype=float)]


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
    }
    if include_arrays:
        out["x"] = _finite_list(block.x)
        out["aux"] = {name: _finite_list(arr) for name, arr in sorted(block.aux.items())}
    return out
