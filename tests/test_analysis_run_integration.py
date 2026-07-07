from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.analysis_runner import execute_analysis_run
from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
from sersflow.infra.analysis_store import count_spectrum_rows, create_run_pending, get_run
from sersflow.infra.datasets_store import create_dataset
from sersflow.infra.sessions_store import create_session


def test_analysis_run_completes_with_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))

    batch = "b1"
    (tmp_path / batch).mkdir()
    f = tmp_path / batch / "s.txt"
    f.write_text("wn\tint\n100\t1\n200\t5\n300\t2\n", encoding="utf-8")
    rel = f"{batch}/s.txt"

    md = DatasetMetadata(name="t")
    spectra = [SpectrumRef(spectrum_id="sp_1", relative_path=rel, record_index=None)]
    ds = create_dataset(owner_user_id="dev", metadata=md, spectra=spectra)

    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="spectral_intensities",
                params={
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
            ),
        ]
    )
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
    assert rec.feature_columns_json
    assert "I_p1" in rec.feature_columns_json


def test_analysis_run_completes_without_spectral_intensities_uses_fallback_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pipelines without spectral_intensities still produce a feature table (default probe)."""
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))

    batch = "b1"
    (tmp_path / batch).mkdir()
    f = tmp_path / batch / "s.txt"
    f.write_text("wn\tint\n100\t1\n200\t5\n300\t2\n", encoding="utf-8")
    rel = f"{batch}/s.txt"

    md = DatasetMetadata(name="t")
    spectra = [SpectrumRef(spectrum_id="sp_1", relative_path=rel, record_index=None)]
    ds = create_dataset(owner_user_id="dev", metadata=md, spectra=spectra)

    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="crop",
                params={"min_x": 150.0, "max_x": 250.0},
            ),
        ]
    )
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
    assert rec.feature_columns_json
    assert "I_analysis_fallback" in rec.feature_columns_json


def test_analysis_run_full_dataset_ignores_session_random_subset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Session preview may be random n=1; analysis still stores one row per dataset spectrum."""
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))

    batch = "b1"
    (tmp_path / batch).mkdir()
    spectra: list[SpectrumRef] = []
    for i in range(3):
        f = tmp_path / batch / f"s{i}.txt"
        f.write_text("wn\tint\n100\t1\n200\t5\n300\t2\n", encoding="utf-8")
        rel = f"{batch}/s{i}.txt"
        spectra.append(SpectrumRef(spectrum_id=f"sp_{i}", relative_path=rel, record_index=None))

    md = DatasetMetadata(name="t")
    ds = create_dataset(owner_user_id="dev", metadata=md, spectra=spectra)

    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="spectral_intensities",
                params={
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
            ),
        ]
    )
    sess = create_session(
        dataset_id=ds.dataset_id,
        pipeline=pipe,
        subset=SubsetStrategy(kind="random", n=1, seed=999),
    )

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
    assert count_spectrum_rows(run_id) == 3
