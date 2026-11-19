"""Volume (X x Y x Z) map support: WDF flat spectra, depth slicing, axis persistence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.core.io import read_wdf
from sersflow.core.models.datasets import MapDataset
from sersflow.core.plot.service import map_grid_info, map_z_levels, plot_map_points
from sersflow.infra.datasets_store import create_dataset, spectrum_export_lookup


def _volume(nx: int = 3, ny: int = 2, nz: int = 4, nw: int = 5) -> MapDataset:
    xs, ys, zs = np.meshgrid(np.arange(nx, dtype=float), np.arange(ny, dtype=float), np.arange(nz) * 5.0 - 10.0)
    # X fastest, then Y, then Z (WiRE ordering)
    order = np.lexsort((xs.ravel(), ys.ravel(), zs.ravel()))
    xp, yp, zp = xs.ravel()[order], ys.ravel()[order], zs.ravel()[order]
    spectra = np.random.default_rng(0).random((xp.size, nw))
    return MapDataset(kind="map", x=np.linspace(100, 200, nw), spectra=spectra, xpos=xp, ypos=yp, zpos=zp)


def test_wdf_flat_spectra_loads_as_volume_map(monkeypatch: pytest.MonkeyPatch) -> None:
    ds = _volume()
    flat = ds.spectra.ravel()
    fake = SimpleNamespace(
        measurement_type=3,
        xdata=ds.x,
        spectra=flat,
        xpos=ds.xpos,
        ypos=ds.ypos,
        zpos=ds.zpos,
    )
    monkeypatch.setattr(read_wdf, "WDFReader", lambda _p: fake)
    out = read_wdf.read_file_wdf(Path("x.wdf"))
    assert isinstance(out, MapDataset)
    assert out.spectra.shape == ds.spectra.shape
    assert out.zpos is not None and np.unique(out.zpos).size == 4


def test_flat_map_has_no_z() -> None:
    ds = _volume(nz=1)
    flat = MapDataset(kind="map", x=ds.x, spectra=ds.spectra, xpos=ds.xpos, ypos=ds.ypos)
    assert map_z_levels(flat) == []


def test_grid_info_slices_by_depth() -> None:
    ds = _volume()
    assert map_z_levels(ds) == [-10.0, -5.0, 0.0, 5.0]
    for zi in range(4):
        _, _, grid, n = map_grid_info(ds, z_index=zi)
        idx = sorted(i for row in grid for i in row if i is not None)
        assert n == 24
        assert idx == list(range(zi * 6, zi * 6 + 6))


def test_map_point_labels_include_depth() -> None:
    fig = plot_map_points(_volume(), indices=[6])
    assert "z=-5" in fig["data"][0]["name"]


def test_store_persists_axis_z_for_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "vol.db"))
    monkeypatch.setattr("sersflow.infra.datasets_store.resolve_uploaded_path", lambda _r, _p: tmp_path / "f.wdf")
    ds = _volume()
    monkeypatch.setattr("sersflow.infra.datasets_store.load_dataset", lambda _p: ds)
    refs = [SpectrumRef(spectrum_id=f"s{i}", relative_path="b/v.wdf", record_index=i) for i in (0, 7, 23)]
    rec = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="v"), spectra=refs)
    lu = spectrum_export_lookup(rec.dataset_id)
    assert lu["s0"]["axis_z"] == pytest.approx(-10.0)
    assert lu["s7"]["axis_z"] == pytest.approx(-5.0)
    assert lu["s23"]["axis_z"] == pytest.approx(5.0)
    assert lu["s7"]["axis_map_x"] == pytest.approx(1.0)
