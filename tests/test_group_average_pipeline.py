from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.analysis_runner import execute_analysis_run
from sersflow.api.services.pipeline_qc import apply_pipeline_qc_filters, pipeline_without_qc_steps
from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.infra.analysis_store import count_spectrum_rows, create_run_pending, get_run
from sersflow.infra.datasets_store import create_dataset
from sersflow.infra.derived_spectra_store import get_derived_spectra, list_derived_spectra
from sersflow.infra.sessions_store import create_session
from sersflow.infra.upload_labels_store import upsert_upload_labels, with_connection


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir()
    spectra = []
    con = with_connection()
    try:
        # (id, current_density, level)
        for sid, cur, level in [("sp_a", 10.0, 1.0), ("sp_b", 10.0, 3.0), ("sp_c", 20.0, 5.0), ("sp_d", 20.0, 7.0)]:
            f = tmp_path / "b1" / f"{sid}.txt"
            f.write_text(f"wn\tint\n100\t{level}\n200\t{level * 2}\n300\t{level}\n", encoding="utf-8")
            rel = f"b1/{sid}.txt"
            upsert_upload_labels(con, relative_path=rel, labels={"current_density": cur})
            spectra.append(SpectrumRef(spectrum_id=sid, relative_path=rel, record_index=None))
    finally:
        con.close()
    return create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="t"), spectra=spectra)


def _pipe() -> Pipeline:
    return Pipeline(
        steps=[
            PipelineStep(name="crop", params={"min_x": 100.0, "max_x": 300.0}, step_id="1"),
            PipelineStep(
                name="group_average",
                params={"mode": "by_label", "group_by": "current_density"},
                step_id="2",
            ),
            PipelineStep(name="crop", params={"min_x": 150.0, "max_x": 300.0}, step_id="3"),
        ]
    )


def test_group_average_replaces_cohort_and_runs_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = _setup(tmp_path, monkeypatch)
    pipe = _pipe()
    refs, reports = apply_pipeline_qc_filters(
        dataset=ds, pipeline=pipe, refs=list(ds.spectra), cache_namespace="t", strict=True
    )
    assert len(refs) == 2
    assert reports[0].step_name == "group_average"
    members = sorted(sorted(v) for v in reports[0].meta["members_by_group"].values())
    assert members == [["sp_a", "sp_b"], ["sp_c", "sp_d"]]

    eff = pipeline_without_qc_steps(pipe)
    assert [s.enabled for s in eff.steps] == [False, True]  # prefix kept disabled, group step removed
    final = run_pipeline(
        inputs=refs, pipeline=eff, cache=InProcessLRUCache(max_items=64), config=EngineConfig(cache_namespace="t"), strict=True
    )
    # after the second crop (150..300) y[0] is the wn=200 point: mean(2, 6) and mean(10, 14)
    assert {round(float(xy.y[0]), 6) for xy in final.values()} == {4.0, 12.0}
    assert all(xy.x.min() >= 150.0 for xy in final.values())

    # derived spectra are registered and carry labels / members
    recs = get_derived_spectra(dataset_id=ds.dataset_id, spectrum_ids=[r.spectrum_id for r in refs])
    assert len(recs) == 2
    assert {r.labels["spectrum_role"] for r in recs.values()} == {"group_mean"}
    assert {r.labels["current_density"] for r in recs.values()} == {10.0, 20.0}
    assert len(list_derived_spectra(dataset_id=ds.dataset_id)) == 2


def test_group_ids_are_stable_across_reruns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = _setup(tmp_path, monkeypatch)
    pipe = _pipe()
    r1, _ = apply_pipeline_qc_filters(dataset=ds, pipeline=pipe, refs=list(ds.spectra), cache_namespace="t", strict=True)
    pipe2 = _pipe()
    pipe2.steps[0].params = {"min_x": 100.0, "max_x": 250.0}  # different upstream processing
    r2, _ = apply_pipeline_qc_filters(dataset=ds, pipeline=pipe2, refs=list(ds.spectra), cache_namespace="t", strict=True)
    assert sorted(r.spectrum_id for r in r1) == sorted(r.spectrum_id for r in r2)
    assert len(list_derived_spectra(dataset_id=ds.dataset_id)) == 2  # updated in place, not duplicated


def test_suffix_cannot_reference_prefix_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = _setup(tmp_path, monkeypatch)
    pipe = _pipe()
    pipe.steps[2] = PipelineStep(
        name="crop", params={"min_x": 150.0}, step_id="3", input_from="after_step", after_step_id="1"
    )
    with pytest.raises(ValueError, match="references a step before it"):
        apply_pipeline_qc_filters(dataset=ds, pipeline=pipe, refs=list(ds.spectra), cache_namespace="t", strict=True)


def test_analysis_run_over_group_averages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = _setup(tmp_path, monkeypatch)
    pipe = _pipe()
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
    assert rec is not None and rec.status == "completed", getattr(rec, "error", None)
    assert count_spectrum_rows(run_id) == 2
