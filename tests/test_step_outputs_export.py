"""Step-outputs export: CSV layout and engine collection of per-step outputs."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.services.step_outputs_export_runner import list_pipeline_steps_for_export, step_outputs_csv_bytes
from sersflow.core.pipeline.engine import RAW_COLLECT_TOKEN, EngineConfig, run_pipeline_parallel_no_cache
from sersflow.core.spectrum import XY


def _rows(payload: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(payload.decode("utf-8"))))


def test_csv_same_grid_is_one_column_shifted_grid_is_a_pair():
    raw = XY(x=np.array([1.0, 2.0, 3.0]), y=np.array([10.0, 20.0, 30.0]))
    smooth = XY(x=raw.x.copy(), y=np.array([11.0, 21.0, 31.0]))
    cropped = XY(x=np.array([2.0, 3.0]), y=np.array([5.0, 6.0]))
    rows = _rows(
        step_outputs_csv_bytes(raw=raw, step_outputs=[("s1_smooth", smooth), ("s2_crop", cropped), ("s3_fit", None)])
    )
    assert rows[0] == ["x_raw", "y_raw", "s1_smooth", "s2_crop_x", "s2_crop_y", "s3_fit"]
    assert rows[1] == ["1.0", "10.0", "11.0", "2.0", "5.0", ""]
    assert rows[3] == ["3.0", "30.0", "31.0", "", "", ""]


def test_list_steps_labels_fitting_region():
    pipe = Pipeline.model_validate(
        {
            "technique_family": "xps",
            "steps": [
                {"name": "fitting", "step_id": "vb", "params": {"xps_region": "all valence bands"}},
                {"name": "smoothing", "step_id": "sm", "enabled": False, "params": {}},
                {"name": "fitting", "step_id": "o1s", "params": {"xps_region": "O1s"}},
            ],
        }
    )
    items = list_pipeline_steps_for_export(pipe)
    assert [(it["step_num"], it["label"]) for it in items] == [
        (1, "s1_fitting_all_valence_bands"),
        (3, "s3_fitting_O1s"),
    ]


def test_engine_collects_raw_and_step_outputs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "t.txt").write_text("wn\tint\n100\t10\n200\t20\n300\t40\n", encoding="utf-8")
    steps = [
        {"name": "crop", "params": {"min_x": 150.0, "max_x": 350.0}, "enabled": True},
        {"name": "normalize", "params": {"method": "max"}, "enabled": True},
    ]
    final, per_out = run_pipeline_parallel_no_cache(
        inputs=[{"spectrum_id": "s1", "relative_path": "a/t.txt", "record_index": None}],
        pipeline_steps=steps,
        config=EngineConfig(),
        step_nums=[1, 2],
        collect_steps={RAW_COLLECT_TOKEN, "crop__1"},
    )
    got = per_out["s1"]
    assert set(got) == {RAW_COLLECT_TOKEN, "crop__1"}
    np.testing.assert_allclose(got[RAW_COLLECT_TOKEN].x, [100.0, 200.0, 300.0])
    np.testing.assert_allclose(got["crop__1"].y, [20.0, 40.0])
    np.testing.assert_allclose(final["s1"].y, [0.5, 1.0])
