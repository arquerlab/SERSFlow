from __future__ import annotations

import io

import pytest

pytest.importorskip("pyarrow")
import pyarrow.parquet as pq

from sersflow.api.services.observation_export import write_observation_wide_parquet_bytes


def test_write_observation_wide_parquet_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_iter(*, run_id: str, chunk_size: int = 500):
        yield "s1", {"I_a": 1.0, "I_b": None}
        yield "s2", {"I_a": 2.0, "I_b": 3.0}

    monkeypatch.setattr(
        "sersflow.api.services.observation_export.iter_spectrum_rows",
        fake_iter,
    )
    lookup = {
        "s1": {
            "relative_path": "f.txt",
            "axis_time_s": 1.0,
            "axis_map_x": None,
            "axis_map_y": None,
            "grid_nx": 2,
            "grid_ny": 2,
            "file_kind": "map",
        },
        "s2": {
            "relative_path": "f.txt",
            "axis_time_s": 2.0,
            "axis_map_x": None,
            "axis_map_y": None,
            "grid_nx": 2,
            "grid_ny": 2,
            "file_kind": "map",
        },
    }
    blob = write_observation_wide_parquet_bytes(
        run_id="r1",
        feature_keys=["I_a", "I_b"],
        spectrum_lookup=lookup,
        labels_by_path={"f.txt": {"lab": "x"}},
        join_labels=True,
        join_axes=True,
        max_rows=None,
    )
    t = pq.read_table(io.BytesIO(blob))
    assert t.num_rows == 2
    assert "spectrum_id" in t.column_names
    assert "meta_lab" in t.column_names
