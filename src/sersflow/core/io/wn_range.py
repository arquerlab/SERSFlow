"""Wavenumber span and spectrum count from loaded datasets (upload metadata)."""

from __future__ import annotations

import numpy as np

from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset


def dataset_wn_range_cm1(ds: SpectrumDataset | SeriesDataset | MapDataset) -> tuple[float, float]:
    """Min/max Raman shift (cm⁻¹) from the shared wavenumber axis."""
    x = np.asarray(ds.x, dtype=float)
    if x.size == 0:
        return float("nan"), float("nan")
    return float(np.min(x)), float(np.max(x))


def dataset_spectrum_count(ds: SpectrumDataset | SeriesDataset | MapDataset) -> int:
    """Number of spectra (rows) in the dataset."""
    if isinstance(ds, SpectrumDataset):
        return 1
    if isinstance(ds, (SeriesDataset, MapDataset)):
        return int(ds.spectra.shape[0])
    raise TypeError(f"Unsupported dataset type: {type(ds)}")
