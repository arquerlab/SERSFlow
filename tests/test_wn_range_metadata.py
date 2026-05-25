from __future__ import annotations

import numpy as np

from sersflow.core.io.wn_range import dataset_spectrum_count, dataset_wn_range_cm1
from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset


def test_spectrum_dataset_range_and_count() -> None:
    x = np.array([100.0, 200.0, 300.0])
    y = np.ones_like(x)
    ds = SpectrumDataset(kind="spectrum", x=x, y=y)
    lo, hi = dataset_wn_range_cm1(ds)
    assert lo == 100.0 and hi == 300.0
    assert dataset_spectrum_count(ds) == 1


def test_series_count() -> None:
    x = np.linspace(0, 10, 5)
    spectra = np.zeros((3, 5))
    axis = np.array([0.0, 1.0, 2.0])
    ds = SeriesDataset(kind="series", x=x, spectra=spectra, axis=axis, axis_name="time_s")
    assert dataset_spectrum_count(ds) == 3
