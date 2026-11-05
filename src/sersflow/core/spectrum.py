from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sersflow.core.models.datasets import (
    Dataset,
    MapDataset,
    MultiSpectrumDataset,
    SeriesDataset,
    SpectrumDataset,
)


@dataclass(frozen=True)
class XY:
    x: np.ndarray
    y: np.ndarray
    var: np.ndarray | None = None
    """
    Per-point variance of ``y`` from counting statistics (F1), in y units squared, or None.

    Set at load for multi-block XPS files from the RAW counts and kept only by steps that preserve
    Poisson statistics (crop, x-calibration, static baseline subtraction, normalisation, cosmic-ray
    removal). Any other step builds a new XY without it, so weighting falls back to unweighted.
    """
    var_kind: str | None = None
    """``absolute`` (raw counts: chi2 has an absolute meaning) or ``relative`` (var = g * y, gain unknown)."""

    def keep_var(self, x: np.ndarray, y: np.ndarray, *, mask: np.ndarray | None = None, scale: float = 1.0) -> "XY":
        """New XY that carries this spectrum's variance (optionally masked and scaled by ``scale**2``)."""
        if self.var is None:
            return XY(x=x, y=y)
        v = self.var if mask is None else self.var[mask]
        if v.shape != np.shape(y):
            return XY(x=x, y=y)
        return XY(x=x, y=y, var=v * float(scale) ** 2, var_kind=self.var_kind)


# Sentinel for spectra skipped in batch runs (missing file, invalid index, unrecoverable step failure).
EMPTY_XY = XY(x=np.array([], dtype=float), y=np.array([], dtype=float))


_INTEGER_TOL = 1e-6


def _is_integer_like(a: np.ndarray) -> bool:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return False
    return bool(np.mean(np.abs(a - np.round(a)) <= _INTEGER_TOL * np.maximum(1.0, np.abs(a))) >= 0.99)


def poisson_variance_from_meta(y: np.ndarray, meta: dict | None) -> tuple[np.ndarray, str]:
    """
    Counting-statistics variance of RAW ``y`` (F1).

    - integer counts per channel: var = max(y, 1)                       -> ``absolute``
    - counts/s with dwell and scans known and integer total counts:
      var = max(y * s, 1) / s**2, s = dwell * scans                       -> ``absolute``
    - anything else (scaled / normalised / averaged "counts", unknown units): var = max(y, floor),
      the Poisson shape with an unknown gain g, estimated by the fit       -> ``relative``
    The floor (1e-3 of max |y|) keeps near-zero channels from getting infinite weight.
    """
    from sersflow.core.io.read_vms import count_statistics

    yy = np.asarray(y, dtype=float)
    finite = yy[np.isfinite(yy)]
    floor = max(1e-3 * float(np.max(np.abs(finite))) if finite.size else 0.0, 1e-12)
    st = count_statistics(dict(meta or {}))
    scale = st.get("counts_scale")
    if st.get("y_unit") in ("counts", "cps") and scale:
        counts = yy * float(scale)
        if _is_integer_like(counts):
            return np.maximum(counts, 1.0) / float(scale) ** 2, "absolute"
    return np.maximum(yy, floor), "relative"


def extract_xy(ds: Dataset, *, record_index: int | None = None) -> XY:
    """
    Extract a single spectrum (x,y) from a loaded dataset.

    - SpectrumDataset: returns the only spectrum.
    - SeriesDataset/MapDataset/MultiSpectrumDataset: returns row ``record_index`` (default 0).
    """
    if isinstance(ds, SpectrumDataset):
        return XY(x=ds.x, y=ds.y)

    idx = int(record_index or 0)
    if isinstance(ds, SeriesDataset):
        if idx < 0 or idx >= ds.spectra.shape[0]:
            raise IndexError(f"record_index out of range: {idx}")
        return XY(x=ds.x, y=ds.spectra[idx, :])

    if isinstance(ds, MapDataset):
        if idx < 0 or idx >= ds.spectra.shape[0]:
            raise IndexError(f"record_index out of range: {idx}")
        return XY(x=ds.x, y=ds.spectra[idx, :])

    if isinstance(ds, MultiSpectrumDataset):
        if idx < 0 or idx >= len(ds.xs):
            raise IndexError(f"record_index out of range: {idx}")
        # Multi-block files are XPS/XAS (VAMAS, NeXus, Prodigy): carry counting variance from the raw y.
        meta = ds.meta[idx] if ds.meta and idx < len(ds.meta) else None
        y = np.asarray(ds.ys[idx], dtype=float)
        var, kind = poisson_variance_from_meta(y, meta)
        return XY(x=ds.xs[idx], y=ds.ys[idx], var=var, var_kind=kind)

    raise TypeError(f"Unsupported dataset type: {type(ds)}")
