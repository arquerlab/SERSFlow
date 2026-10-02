from __future__ import annotations

from pathlib import Path

import numpy as np

from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.read_vms import filter_meta_indices
from sersflow.core.models.datasets import MultiSpectrumDataset, SpectrumDataset
from sersflow.core.plot.service import plot_multi_points, plot_spectrum
from sersflow.core.qc.metadata_filter import evaluate_filters
from tests.test_vms_loader import write_mixed_region_vms


def test_plot_multi_points_multiple_traces(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    ds = load_dataset(p)
    assert isinstance(ds, MultiSpectrumDataset)
    fig = plot_multi_points(ds, indices=[0, 3], max_traces=30)
    assert len(fig["data"]) == 2


def test_plot_multi_points_cap(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    ds = load_dataset(p)
    fig = plot_multi_points(ds, indices=[0, 1, 2, 3, 4], max_traces=2)
    assert len(fig["data"]) == 2


def test_multi_info_shape_via_dataset(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    ds = load_dataset(p)
    assert isinstance(ds, MultiSpectrumDataset)
    assert len(ds.meta) == 5
    # Client-side filter path: mode averages then region filter.
    mode_idx = filter_meta_indices(ds.meta, "averages")
    assert mode_idx == [0, 3]
    matched = [
        i
        for i in mode_idx
        if evaluate_filters(ds.meta[i], [{"field": "xps_region", "op": "in", "values": ["C1s"]}])
    ]
    assert matched == [0]


def test_non_multi_is_not_multi_spectrum() -> None:
    x = np.linspace(0, 1, 5)
    y = np.ones_like(x)
    ds = SpectrumDataset(kind="spectrum", x=x, y=y)
    assert not isinstance(ds, MultiSpectrumDataset)
    fig = plot_spectrum(ds, spectrum_index=0, title="single")
    assert len(fig["data"]) == 1


def test_plot_spectrum_index_zero_on_multi_still_works(tmp_path: Path) -> None:
    """Regression: single-trace plot_spectrum with index 0 remains valid for VMS."""
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    ds = load_dataset(p)
    fig = plot_spectrum(ds, spectrum_index=0, title="first")
    assert len(fig["data"]) == 1
