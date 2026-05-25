"""Tests for _populate_axes_for_dataset (per-file kind: single / series / map)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset
from sersflow.infra.datasets_store import create_dataset, spectrum_export_lookup
from sersflow.infra.sqlite_db import connect


@pytest.fixture
def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "axes.db"))
    return tmp_path


def test_populate_axes_single_spectrum_file(db_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sersflow.infra.datasets_store.resolve_uploaded_path",
        lambda _root, _rel: db_env / "f.txt",
    )

    def fake_load(_p: Path) -> SpectrumDataset:
        x = np.linspace(100, 2000, 50)
        return SpectrumDataset(kind="spectrum", x=x, y=np.sin(x / 200.0))

    monkeypatch.setattr("sersflow.infra.datasets_store.load_dataset", fake_load)

    spectra = [SpectrumRef(spectrum_id="s1", relative_path="batch/a.txt", record_index=None)]
    rec = create_dataset(metadata=DatasetMetadata(name="t"), spectra=spectra)
    lu = spectrum_export_lookup(rec.dataset_id)
    assert lu["s1"]["axis_time_s"] is None
    assert lu["s1"]["axis_map_x"] is None
    assert lu["s1"]["file_kind"] == "single"

    with connect() as con:
        row = con.execute(
            "SELECT kind, grid_nx, grid_ny FROM dataset_file_meta WHERE dataset_id=? AND relative_path=?",
            (rec.dataset_id, "batch/a.txt"),
        ).fetchone()
    assert row is not None
    assert row["kind"] == "single"
    assert int(row["grid_nx"]) == 1 and int(row["grid_ny"]) == 1


def test_populate_axes_series_time_axis(db_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sersflow.infra.datasets_store.resolve_uploaded_path",
        lambda _root, _rel: db_env / "f.txt",
    )

    def fake_load(_p: Path) -> SeriesDataset:
        x = np.linspace(100, 2000, 10)
        spec = np.random.default_rng(0).random((3, 10))
        axis = np.array([0.0, 1.5, 3.0])
        return SeriesDataset(kind="series", x=x, spectra=spec, axis=axis, axis_name="t")

    monkeypatch.setattr("sersflow.infra.datasets_store.load_dataset", fake_load)

    spectra = [
        SpectrumRef(spectrum_id="s0", relative_path="batch/series.txt", record_index=0),
        SpectrumRef(spectrum_id="s1", relative_path="batch/series.txt", record_index=1),
        SpectrumRef(spectrum_id="s2", relative_path="batch/series.txt", record_index=2),
    ]
    rec = create_dataset(metadata=DatasetMetadata(name="t"), spectra=spectra)
    lu = spectrum_export_lookup(rec.dataset_id)
    assert lu["s0"]["axis_time_s"] == pytest.approx(0.0)
    assert lu["s1"]["axis_time_s"] == pytest.approx(1.5)
    assert lu["s2"]["axis_time_s"] == pytest.approx(3.0)
    assert lu["s0"]["file_kind"] == "series"


def test_populate_axes_map_positions(db_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sersflow.infra.datasets_store.resolve_uploaded_path",
        lambda _root, _rel: db_env / "f.txt",
    )

    def fake_load(_p: Path) -> MapDataset:
        x = np.linspace(100, 2000, 8)
        xpos = np.array([0.0, 1.0, 0.0, 1.0])
        ypos = np.array([0.0, 0.0, 1.0, 1.0])
        spec = np.random.default_rng(1).random((4, 8))
        return MapDataset(kind="map", x=x, spectra=spec, xpos=xpos, ypos=ypos)

    monkeypatch.setattr("sersflow.infra.datasets_store.load_dataset", fake_load)

    spectra = [
        SpectrumRef(spectrum_id="m0", relative_path="batch/map.wdf", record_index=0),
        SpectrumRef(spectrum_id="m3", relative_path="batch/map.wdf", record_index=3),
    ]
    rec = create_dataset(metadata=DatasetMetadata(name="t"), spectra=spectra)
    lu = spectrum_export_lookup(rec.dataset_id)
    assert lu["m0"]["axis_map_x"] == pytest.approx(0.0)
    assert lu["m0"]["axis_map_y"] == pytest.approx(0.0)
    assert lu["m3"]["axis_map_x"] == pytest.approx(1.0)
    assert lu["m3"]["axis_map_y"] == pytest.approx(1.0)
    assert lu["m0"]["file_kind"] == "map"
