"""Wavenumber / energy span and spectrum count from loaded datasets (upload metadata)."""

from __future__ import annotations

import numpy as np

from sersflow.core.models.datasets import MapDataset, MultiSpectrumDataset, SeriesDataset, SpectrumDataset


def dataset_wn_range_cm1(
    ds: SpectrumDataset | SeriesDataset | MapDataset | MultiSpectrumDataset,
) -> tuple[float, float]:
    """Min/max abscissa from the shared axis (or across all axes for multi-block)."""
    if isinstance(ds, MultiSpectrumDataset):
        if not ds.xs:
            return float("nan"), float("nan")
        mins = [float(np.min(x)) for x in ds.xs if np.asarray(x).size]
        maxs = [float(np.max(x)) for x in ds.xs if np.asarray(x).size]
        if not mins:
            return float("nan"), float("nan")
        return min(mins), max(maxs)
    x = np.asarray(ds.x, dtype=float)
    if x.size == 0:
        return float("nan"), float("nan")
    return float(np.min(x)), float(np.max(x))


def dataset_spectrum_count(
    ds: SpectrumDataset | SeriesDataset | MapDataset | MultiSpectrumDataset,
) -> int:
    """Number of spectra (rows / blocks) in the dataset."""
    if isinstance(ds, SpectrumDataset):
        return 1
    if isinstance(ds, (SeriesDataset, MapDataset)):
        return int(ds.spectra.shape[0])
    if isinstance(ds, MultiSpectrumDataset):
        return len(ds.xs)
    raise TypeError(f"Unsupported dataset type: {type(ds)}")
