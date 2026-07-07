from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.analysis_runner import execute_analysis_run
from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
from sersflow.core.metrics.feature_operations import evaluate_formula
from sersflow.core.metrics.integration_features import collect_integration_features_for_pipeline
from sersflow.core.pipeline.steps import DEFAULT_STEPS
from sersflow.core.spectrum import XY
from sersflow.infra.analysis_store import count_spectrum_rows, create_run_pending, get_run, iter_spectrum_rows
from sersflow.infra.datasets_store import create_dataset
from sersflow.infra.sessions_store import create_session


def test_collect_integration_feature_matches_trapezoid_area() -> None:
    xy = XY(x=np.array([0.0, 1.0, 2.0]), y=np.array([0.0, 1.0, 2.0]))
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="spectral_integrations",
                params={"windows": [{"id": "band", "min_cm1": 0.0, "max_cm1": 2.0, "mode": "signed"}]},
            )
        ]
    )

    ordered, feats = collect_integration_features_for_pipeline(xy, pipe)

    assert ordered == ["area_band"]
    assert feats["area_band"] == pytest.approx(2.0)


def test_feature_operation_formula_uses_braced_variables_safely() -> None:
    value = evaluate_formula("{p1_pos}/{p2_amp}**0.25", {"p1_pos": 16.0, "p2_amp": 16.0})

    assert value == pytest.approx(8.0)
    assert evaluate_formula("__import__('os').system('echo nope')", {}) is None
    assert evaluate_formula("{missing}/2", {}) is None
    assert evaluate_formula("{a}/0", {"a": 1.0}) is None


def test_spectrum_derivative_transform() -> None:
    xy = XY(x=np.array([0.0, 1.0, 2.0, 3.0]), y=np.array([0.0, 1.0, 4.0, 9.0]))

    out = DEFAULT_STEPS["spectrum_derivative"].transform(xy, {"method": "gradient", "order": 1})

    assert out.x.tolist() == [0.0, 1.0, 2.0, 3.0]
    assert out.y == pytest.approx([0.0, 2.0, 4.0, 6.0])


def test_reference_transform_subtracts_and_divides_interpolated_reference() -> None:
    xy = XY(x=np.array([0.0, 1.0, 2.0]), y=np.array([2.0, 4.0, 6.0]))
    params = {"_reference_x": [0.0, 1.0, 2.0], "_reference_y": [1.0, 2.0, 3.0]}

    sub = DEFAULT_STEPS["reference_transform"].transform(xy, {**params, "operation": "subtract"})
    div = DEFAULT_STEPS["reference_transform"].transform(xy, {**params, "operation": "divide"})

    assert sub.y == pytest.approx([1.0, 2.0, 3.0])
    assert div.y == pytest.approx([2.0, 2.0, 2.0])


def test_analysis_run_excludes_reference_and_exports_integration_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))

    batch = "b1"
    (tmp_path / batch).mkdir()
    ref_file = tmp_path / batch / "ref.txt"
    sample_file = tmp_path / batch / "sample.txt"
    ref_file.write_text("wn\tint\n0\t1\n1\t1\n2\t1\n", encoding="utf-8")
    sample_file.write_text("wn\tint\n0\t2\n1\t3\n2\t4\n", encoding="utf-8")

    spectra = [
        SpectrumRef(spectrum_id="ref", relative_path=f"{batch}/ref.txt", record_index=None),
        SpectrumRef(spectrum_id="sample", relative_path=f"{batch}/sample.txt", record_index=None),
    ]
    ds = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="t"), spectra=spectra)
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="reference_transform",
                params={
                    "reference_spectrum_id": "ref",
                    "reference_stage": "raw",
                    "operation": "subtract",
                    "interpolation": "linear",
                },
            ),
            PipelineStep(
                name="spectral_integrations",
                params={"windows": [{"id": "band", "min_cm1": 0.0, "max_cm1": 2.0, "mode": "signed"}]},
            ),
            PipelineStep(
                name="feature_operations",
                params={"operations": [{"id": "half", "formula": "{area_band}/2"}]},
            ),
        ]
    )
    sess = create_session(dataset_id=ds.dataset_id, pipeline=pipe, subset=SubsetStrategy(kind="all"))
    run_id = create_run_pending(
        dataset_id=ds.dataset_id,
        session_id=sess.session_id,
        pipeline_hash=pipeline_hash(pipe),
        subset_hash=subset_hash(SubsetStrategy(kind="all")),
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
    assert count_spectrum_rows(run_id) == 1
    rows = list(iter_spectrum_rows(run_id=run_id))
    assert rows[0][0] == "sample"
    assert rows[0][1]["area_band"] == pytest.approx(4.0)
    assert rows[0][1]["op_half"] == pytest.approx(2.0)
