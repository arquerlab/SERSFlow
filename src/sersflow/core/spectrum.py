from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sersflow.core.models.datasets import Dataset, MapDataset, SeriesDataset, SpectrumDataset


@dataclass(frozen=True)
class XY:
    x: np.ndarray
    y: np.ndarray


def extract_xy(ds: Dataset, *, record_index: int | None = None) -> XY:
    """
    Extract a single spectrum (x,y) from a loaded dataset.

    - SpectrumDataset: returns the only spectrum.
    - SeriesDataset/MapDataset: returns row `record_index` (default 0).
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

    raise TypeError(f"Unsupported dataset type: {type(ds)}")

