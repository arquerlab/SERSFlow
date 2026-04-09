from __future__ import annotations

from pathlib import Path

import numpy as np

from sersflow.core.io.read_txt import read_file_txt
from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_txt_spectrum_contract(tmp_path: Path) -> None:
    p = _write(tmp_path / "spec.txt", "wn\tint\n100\t1\n200\t2\n")
    ds = read_file_txt(p)
    assert isinstance(ds, SpectrumDataset)
    assert ds.kind == "spectrum"
    assert ds.x.shape == ds.y.shape == (2,)


def test_txt_series_contract(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "series.txt",
        "time\twn\tint\n0\t100\t1\n0\t200\t2\n1\t100\t3\n1\t200\t4\n",
    )
    ds = read_file_txt(p)
    assert isinstance(ds, SeriesDataset)
    assert ds.kind == "series"
    assert ds.x.shape == (2,)
    assert ds.spectra.shape == (2, 2)
    assert ds.axis.shape == (2,)
    assert np.allclose(ds.axis, [0, 1])


def test_txt_map_contract(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "map.txt",
        "x\ty\twn\tint\n0\t0\t100\t1\n0\t0\t200\t2\n1\t0\t100\t3\n1\t0\t200\t4\n",
    )
    ds = read_file_txt(p)
    assert isinstance(ds, MapDataset)
    assert ds.kind == "map"
    assert ds.x.shape == (2,)
    assert ds.spectra.shape == (2, 2)
    assert ds.xpos.shape == (2,)
    assert ds.ypos.shape == (2,)

