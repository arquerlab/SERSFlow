from __future__ import annotations

import numpy as np

from sersflow.core.models.datasets import SpectrumDataset
from sersflow.core.plot.service import plot_spectrum


def test_plot_spectrum_returns_plotly_json() -> None:
    ds = SpectrumDataset(kind="spectrum", x=np.array([100.0, 200.0]), y=np.array([1.0, 2.0]))
    fig = plot_spectrum(ds, title="t")
    assert isinstance(fig, dict)
    assert "data" in fig and "layout" in fig
    assert isinstance(fig["data"], list) and fig["data"]

