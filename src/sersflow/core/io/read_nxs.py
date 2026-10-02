"""Load diamond-style NeXus/HDF5 XPS ``.nxs`` files as MultiSpectrumDataset."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from sersflow.core.io.read_vms import classify_block_role, derive_xps_region

logger = logging.getLogger(__name__)

_SPECTRUM_NAME_RE = re.compile(r"^spectrum(?:_(\d+))?$", re.IGNORECASE)


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if hasattr(v, "shape") and getattr(v, "shape", None) is not None:
            arr = np.asarray(v).ravel()
            if arr.size == 0:
                return default
            return float(arr[0])
        return float(v)
    except Exception:
        return default


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if hasattr(v, "shape") and getattr(v, "shape", None) is not None:
            arr = np.asarray(v).ravel()
            if arr.size == 0:
                return default
            return int(arr[0])
        return int(v)
    except Exception:
        return default


def _read_1d_spectrum(dset: Any) -> np.ndarray | None:
    try:
        arr = np.asarray(dset[()], dtype=float)
    except Exception:
        return None
    if arr.ndim == 2 and arr.shape[0] == 1:
        arr = arr[0, :]
    elif arr.ndim > 1:
        arr = arr.reshape(-1)
    if arr.size == 0 or not np.any(np.isfinite(arr)):
        return None
    return np.asarray(arr, dtype=float)


def _sanitize_region_token(region_key: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]+", "", str(region_key or "").strip())
    return token or "unknown"


def _spectrum_role_from_name(sname: str) -> tuple[str, int | None]:
    m = _SPECTRUM_NAME_RE.match(str(sname or "").strip())
    if not m:
        return "average", None
    idx = m.group(1)
    if idx is None:
        return "average", None
    return "individual", int(idx)


def _iter_region_spectrum_names(data_group: Any, n_iter: int) -> list[str]:
    names = ["spectrum"] + [f"spectrum_{i}" for i in range(1, max(0, n_iter) + 1)]
    present: list[str] = []
    for sname in names:
        if sname in data_group:
            present.append(sname)
    try:
        extras = sorted(
            (
                k
                for k in data_group.keys()
                if _SPECTRUM_NAME_RE.match(str(k)) and str(k) not in present
            ),
            key=lambda k: (0 if str(k).lower() == "spectrum" else 1, str(k)),
        )
        present.extend(extras)
    except Exception:
        pass
    return present


def read_nxs_blocks_with_report(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Parse an XPS NeXus file into block dicts plus a skip report.

    Report keys: ``skipped_regions`` (list of {key, reason}), ``skipped_count``.
    """
    try:
        import h5py
    except ImportError as e:
        raise ImportError(
            "Reading .nxs files requires h5py. Install with: pip install h5py"
        ) from e

    p = Path(path)
    blocks: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    with h5py.File(p, "r") as f:
        entry = f.get("entry")
        if entry is None:
            return [], {"skipped_regions": [], "skipped_count": 0}

        region_keys: list[str] = []
        for key in entry.keys():
            group = entry[key]
            if not isinstance(group, h5py.Group):
                continue
            if "binding_energy" in group:
                region_keys.append(str(key))
            else:
                skipped.append({"key": str(key), "reason": "no_binding_energy"})
        region_keys.sort()

        inst_root = entry.get("instrument", None)
        for region_key in region_keys:
            try:
                data = entry[region_key]
                instrument = (
                    inst_root[region_key]
                    if inst_root is not None and region_key in inst_root
                    else None
                )
                if "binding_energy" not in data:
                    skipped.append({"key": region_key, "reason": "no_binding_energy"})
                    continue
                energy = np.asarray(data["binding_energy"][()], dtype=float).reshape(-1)
                if energy.size == 0:
                    skipped.append({"key": region_key, "reason": "empty_binding_energy"})
                    continue

                n_iter = 0
                if instrument is not None and "number_of_iterations" in instrument:
                    n_iter = max(0, _as_int(instrument["number_of_iterations"][()], 0) - 1)

                excitation_energy = 0.0
                if "excitation_energy" in data:
                    excitation_energy = _as_float(data["excitation_energy"][()], 0.0)

                step_time = 0.0
                total_steps = 0
                total_time = 0.0
                if instrument is not None:
                    if "step_time" in instrument:
                        step_time = _as_float(instrument["step_time"][()], 0.0)
                    if "total_steps" in instrument:
                        total_steps = _as_int(instrument["total_steps"][()], 0)
                    if "total_time" in instrument:
                        total_time = _as_float(instrument["total_time"][()], 0.0)

                region_token = _sanitize_region_token(region_key)
                n_before = len(blocks)
                for sname in _iter_region_spectrum_names(data, n_iter):
                    y = _read_1d_spectrum(data[sname])
                    if y is None:
                        continue
                    n = min(energy.size, y.size)
                    if n <= 0:
                        continue
                    x = energy[:n]
                    yy = y[:n]
                    role, rep = _spectrum_role_from_name(sname)
                    if role == "average":
                        block_name = f"{region_key}_spectrum"
                    else:
                        block_name = f"{region_key}_spectrum_{rep}"
                    role_info = classify_block_role(block_name)
                    blocks.append(
                        {
                            "x": x,
                            "y": yy,
                            "meta": {
                                "xps_region": region_token or derive_xps_region(region_key, None),
                                "xps_species": None,
                                "xps_transition": None,
                                "block_name": block_name,
                                "spectrum_role": role_info["spectrum_role"],
                                "replicate_index": role_info["replicate_index"],
                                "technique": "XPS",
                                "acquired_at": None,
                                "excitation_energy_eV": excitation_energy or None,
                                "step_time": step_time or None,
                                "total_steps": total_steps or None,
                                "total_time": total_time or None,
                                "number_of_iterations": n_iter or None,
                                "nxs_region_key": region_key,
                                "nxs_spectrum_name": sname,
                            },
                        }
                    )
                if len(blocks) == n_before:
                    skipped.append({"key": region_key, "reason": "no_usable_spectra"})
            except Exception as e:
                logger.warning("Skipping NXS region %r in %s (read error)", region_key, p, exc_info=True)
                skipped.append({"key": region_key, "reason": f"read_error:{type(e).__name__}"})
                continue
    report = {"skipped_regions": skipped, "skipped_count": len(skipped)}
    return blocks, report


def read_nxs_blocks(path: str | Path) -> list[dict[str, Any]]:
    """
    Parse an XPS NeXus file into block dicts (x, y, meta).

    Stable order: regions sorted by name; within each region average ``spectrum``
    first, then ``spectrum_1`` … ``spectrum_N``.
    """
    blocks, _report = read_nxs_blocks_with_report(path)
    return blocks


def read_file_nxs(file_path: Path):
    """Load a ``.nxs`` XPS file as MultiSpectrumDataset (one entry per spectrum block)."""
    from sersflow.core.models.datasets import MultiSpectrumDataset

    blocks, report = read_nxs_blocks_with_report(file_path)
    if not blocks:
        raise ValueError(f"NeXus XPS file contains no usable spectrum blocks: {file_path}")
    xs = tuple(np.asarray(b["x"], dtype=float) for b in blocks)
    ys = tuple(np.asarray(b["y"], dtype=float) for b in blocks)
    meta = tuple(dict(b["meta"]) for b in blocks)
    # Surface skip summary on the first block meta for upload enrich callers.
    if report.get("skipped_count"):
        m0 = dict(meta[0])
        m0["nxs_skipped_count"] = int(report["skipped_count"])
        m0["nxs_skipped_regions"] = list(report.get("skipped_regions") or [])
        meta = (m0,) + meta[1:]
    return MultiSpectrumDataset(kind="multi", xs=xs, ys=ys, meta=meta)
