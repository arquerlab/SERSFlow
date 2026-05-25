from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.analysis_runner import execute_analysis_run
from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
from sersflow.infra.analysis_store import create_run_pending, get_run
from sersflow.infra.datasets_store import create_dataset
from sersflow.infra.sessions_store import create_session


def _ui_shaped_pipeline() -> dict:
    """Approximates a small UI-built pipeline: crop → normalize → spectral_intensities."""
    return {
        "steps": [
            {
                "name": "crop",
                "params": {"min_x": 50.0, "max_x": 400.0},
                "enabled": True,
                "step_id": "editor-step-crop",
                "input_from": "previous",
            },
            {
                "name": "normalize",
                "params": {"method": "max"},
                "enabled": True,
                "step_id": "editor-step-norm",
                "input_from": "previous",
            },
            {
                "name": "spectral_intensities",
                "params": {
                    "probes": [
                        {
                            "id": "p1",
                            "target_cm1": 200.0,
                            "acquisition": "fixed",
                            "method": "nearest",
                            "extrapolation": "nan",
                        }
                    ]
                },
                "enabled": True,
                "step_id": "editor-step-int",
                "input_from": "previous",
            },
        ]
    }


def test_ui_shaped_pipeline_validates_and_analysis_run_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))

    raw = _ui_shaped_pipeline()
    pipe = Pipeline.model_validate(raw)

    batch = "b1"
    (tmp_path / batch).mkdir()
    f = tmp_path / batch / "s.txt"
    f.write_text("wn\tint\n100\t1\n200\t5\n300\t2\n", encoding="utf-8")
    rel = f"{batch}/s.txt"

    md = DatasetMetadata(name="t")
    spectra = [SpectrumRef(spectrum_id="sp_1", relative_path=rel, record_index=None)]
    ds = create_dataset(metadata=md, spectra=spectra)

    sess = create_session(dataset_id=ds.dataset_id, pipeline=pipe, subset=SubsetStrategy(kind="all"))
    ph = pipeline_hash(pipe)
    sh = subset_hash(SubsetStrategy(kind="all"))
    run_id = create_run_pending(
        dataset_id=ds.dataset_id,
        session_id=sess.session_id,
        pipeline_hash=ph,
        subset_hash=sh,
        pipeline_json=None,
        label=None,
        pinned=False,
        client_job_key=None,
        params=None,
    )

    execute_analysis_run(run_id=run_id, job_id=None)
    rec = get_run(run_id)
    assert rec is not None
    assert rec.status == "completed"


def test_ui_shaped_baseline_point_pipeline_contract_validates() -> None:
    raw = {
        "steps": [
            {
                "name": "baseline",
                "params": {"method": "mor", "half_window": 30},
                "enabled": True,
                "step_id": "editor-step-base",
                "input_from": "previous",
            },
            {
                "name": "normalize",
                "params": {
                    "method": "baseline_point",
                    "baseline_step_id": "editor-step-base",
                    "point_x": 1000.0,
                },
                "enabled": True,
                "step_id": "editor-step-norm",
                "input_from": "initial",
            },
        ]
    }

    pipe = Pipeline.model_validate(raw)

    assert pipe.steps[1].params["method"] == "baseline_point"
    assert pipe.steps[1].params["baseline_step_id"] == "editor-step-base"
    assert pipe.steps[1].params["point_x"] == 1000.0
