from __future__ import annotations

import csv
import io

import pytest

from sersflow.api.services.observation_export import (
    iter_observation_long_csv_bytes,
    iter_observation_wide_csv_bytes,
)


def _chunks(gen):
    return b"".join(gen).decode("utf-8")


def test_observation_wide_joins_labels_and_axes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_iter(*, run_id: str, chunk_size: int = 500):
        yield "sp1", {"I_p1": 1.5}
        yield "sp2", {"I_p1": 2.5}

    monkeypatch.setattr(
        "sersflow.api.services.observation_export.iter_spectrum_rows",
        fake_iter,
    )

    lookup = {
        "sp1": {
            "relative_path": "batch/f.txt",
            "axis_time_s": 0.1,
            "axis_map_x": 1.0,
            "axis_map_y": 2.0,
            "grid_nx": 3,
            "grid_ny": 4,
            "file_kind": "map",
        },
        "sp2": {
            "relative_path": "batch/f.txt",
            "axis_time_s": None,
            "axis_map_x": None,
            "axis_map_y": None,
            "grid_nx": 3,
            "grid_ny": 4,
            "file_kind": "map",
        },
    }
    labels_by_path = {"batch/f.txt": {"compound": "Cu", "nested": {"k": 1}}}

    raw = _chunks(
        iter_observation_wide_csv_bytes(
            run_id="r1",
            dataset_id="d1",
            feature_keys=["I_p1"],
            spectrum_lookup=lookup,
            labels_by_path=labels_by_path,
            join_labels=True,
            join_axes=True,
            max_rows=None,
        )
    )
    r = csv.reader(io.StringIO(raw))
    rows = list(r)
    header = rows[0]
    assert "spectrum_id" in header and "I_p1" in header
    assert "axis_time_s" in header and "grid_nx" in header
    assert "meta_compound" in header and "meta_nested" in header
    assert len(rows) == 3


def test_observation_long_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_iter(*, run_id: str, chunk_size: int = 500):
        yield "sp1", {"f1": 1.0}

    monkeypatch.setattr(
        "sersflow.api.services.observation_export.iter_spectrum_rows",
        fake_iter,
    )
    lookup = {
        "sp1": {
            "relative_path": "a.txt",
            "axis_time_s": 0.5,
            "axis_map_x": None,
            "axis_map_y": None,
            "grid_nx": 1,
            "grid_ny": 1,
            "file_kind": "single",
        }
    }
    raw = _chunks(
        iter_observation_long_csv_bytes(
            run_id="r1",
            run_id_value="r1",
            dataset_id="d1",
            spectrum_lookup=lookup,
            labels_by_path={"a.txt": {"ph": 7.0}},
            join_labels=True,
            join_axes=True,
            max_spectra=None,
        )
    )
    r = csv.reader(io.StringIO(raw))
    rows = list(r)
    kinds = {row[5] for row in rows[1:]}
    assert kinds == {"feature", "axis", "meta"}
