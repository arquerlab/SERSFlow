"""K2: failed fits are recorded (run warnings, NaN features, success=0, fit_health.csv, MCP), not passed silently."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.core.metrics.fitting_features import collect_fitting_features_for_pipeline
from sersflow.core.pipeline.steps import DEFAULT_STEPS
from sersflow.core.preprocess.fit_status import fit_summary_warnings, summarize_fit_statuses
from sersflow.core.preprocess.fitting import fit_not_applicable_reason
from sersflow.core.spectrum import XY

FIT_PARAMS = {
    "components": [{"component_id": "p1", "component_type": "gaussian"}],
    "p0": [200.0, 10.0, 20.0],
    "bounds_lower": [150.0, 0.0, 1.0],
    "bounds_upper": [250.0, None, 100.0],
}


def _xy(amp: float = 10.0) -> XY:
    x = np.linspace(100.0, 300.0, 201)
    y = amp * np.exp(-4 * np.log(2) * ((x - 200.0) / 20.0) ** 2) + 1.0
    return XY(x=x, y=y)


def _pipe() -> Pipeline:
    return Pipeline(steps=[PipelineStep(name="fitting", params=dict(FIT_PARAMS), step_id="fit1")])


def test_window_outside_spectrum_is_not_applicable() -> None:
    params = dict(FIT_PARAMS, fit_min_x=700.0, fit_max_x=800.0)
    assert fit_not_applicable_reason(_xy(), params) is not None
    assert fit_not_applicable_reason(_xy(), FIT_PARAMS) is None


def test_status_ok_and_not_applicable() -> None:
    st: list[dict] = []
    _, vals = collect_fitting_features_for_pipeline(_xy(), _pipe(), status_out=st)
    assert [s["status"] for s in st] == ["ok"]
    assert any(v is not None for v in vals.values())

    pipe = Pipeline(
        steps=[PipelineStep(name="fitting", params=dict(FIT_PARAMS, fit_min_x=700.0, fit_max_x=800.0))]
    )
    st2: list[dict] = []
    _, vals2 = collect_fitting_features_for_pipeline(_xy(), pipe, status_out=st2)
    assert st2[0]["status"] == "not_applicable"
    assert all(v is None for v in vals2.values())  # not a failure: no success=0 either


def test_invalid_setup_is_failed_with_success_zero() -> None:
    bad = dict(FIT_PARAMS, p0=[200.0, 10.0])  # wrong p0 length
    pipe = Pipeline(steps=[PipelineStep(name="fitting", params=bad, step_id="fit1")])
    st: list[dict] = []
    keys, vals = collect_fitting_features_for_pipeline(_xy(), pipe, status_out=st)
    assert st[0]["status"] == "failed"
    assert "invalid fit setup" in st[0]["reason"]
    success_keys = [k for k in keys if k.endswith("success")]
    assert success_keys and all(vals[k] == 0.0 for k in success_keys)
    assert all(vals[k] is None for k in keys if not k.endswith("success"))


def test_empty_spectrum_is_failed_not_skipped() -> None:
    st: list[dict] = []
    empty = XY(x=np.array([]), y=np.array([]))
    collect_fitting_features_for_pipeline(empty, _pipe(), status_out=st)
    assert st[0]["status"] == "failed" and "empty spectrum" in st[0]["reason"]


def test_fitting_step_passes_raw_spectrum_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    bad = dict(FIT_PARAMS, p0=[200.0, 10.0])
    xy = _xy()
    with caplog.at_level("WARNING"):
        out = DEFAULT_STEPS["fitting"].transform(xy, bad)
    assert np.array_equal(out.y, xy.y)
    assert any("FAILED" in r.message for r in caplog.records)


def test_summary_counts_and_warnings() -> None:
    summary = summarize_fit_statuses(
        {
            "a": [{"status": "ok"}],
            "b": [{"status": "failed", "reason": "boom", "step_id": "fit1", "step_index": 0}],
            "c": [{"status": "not_applicable"}],
            "d": [{"status": "not_converged", "reason": "nfev"}],
        }
    )
    assert summary["n_fits"] == 3
    assert summary["n_failed"] == 1 and summary["n_not_converged"] == 1
    assert [i["spectrum_id"] for i in summary["items"]] == ["b", "d"]
    w = fit_summary_warnings(summary)
    assert any("FAILED" in x for x in w) and any("did not converge" in x for x in w)
    assert fit_summary_warnings(summarize_fit_statuses({"a": [{"status": "ok"}]})) == []


def _run_with_one_failing_fit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    from sersflow.api.services.analysis_runner import execute_analysis_run
    from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
    from sersflow.core.metrics import fitting_features
    from sersflow.infra.analysis_store import create_run_pending
    from sersflow.infra.datasets_store import create_dataset
    from sersflow.infra.sessions_store import create_session

    from sersflow.core.pipeline import engine

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    # The engine keeps a process pool across calls; workers forked by an earlier test still carry
    # that test's env (data dir) and would return empty spectra here.
    engine._reset_pipeline_pool()

    batch = "b1"
    (tmp_path / batch).mkdir()
    spectra = []
    for i, amp in enumerate((10.0, 500.0)):
        xy = _xy(amp)
        f = tmp_path / batch / f"s{i}.txt"
        f.write_text(
            "wn\tint\n" + "".join(f"{a}\t{b}\n" for a, b in zip(xy.x, xy.y)), encoding="utf-8"
        )
        spectra.append(SpectrumRef(spectrum_id=f"sp_{i}", relative_path=f"{batch}/s{i}.txt", record_index=None))
    ds = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="t"), spectra=spectra)

    real_fit = fitting_features.fit_curve

    def flaky_fit(prob):  # deliberately fail the bright spectrum
        if float(np.max(prob.y)) > 100.0:
            raise RuntimeError("deliberate test failure")
        return real_fit(prob)

    monkeypatch.setattr(fitting_features, "fit_curve", flaky_fit)

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
    return run_id


def test_run_records_failed_fit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sersflow.infra.analysis_store import get_run, get_spectrum_features_for_ids

    run_id = _run_with_one_failing_fit(tmp_path, monkeypatch)
    rec = get_run(run_id)
    assert rec is not None and rec.status == "completed"
    data = json.loads(rec.warnings_json)
    ff = data["fit_failures"]
    assert ff["n_fits"] == 2 and ff["n_failed"] == 1 and ff["n_ok"] == 1
    assert ff["items"][0]["spectrum_id"] == "sp_1"
    assert "deliberate test failure" in ff["items"][0]["reason"]
    assert any("FAILED" in w for w in data["warnings"])

    feats = get_spectrum_features_for_ids(run_id=run_id, spectrum_ids=["sp_0", "sp_1"])
    bad = feats["sp_1"]
    assert all(v is None for k, v in bad.items() if not k.endswith("success"))
    assert [v for k, v in bad.items() if k.endswith("success")] == [0.0]
    good = feats["sp_0"]
    assert [v for k, v in good.items() if k.endswith("success")] == [1.0]

    # REST summary
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    body = TestClient(app).get(f"/analysis/runs/{run_id}").json()["run"]
    assert body["fit_failures"]["n_failed"] == 1
    assert body["warnings"]

    # MCP summary (same payload shape the tools return)
    from sersflow.mcp import summarize

    out = summarize.analysis_run_summary({"run": body})
    assert out["fit_failures"]["items"][0]["spectrum_id"] == "sp_1"
    compact = summarize.analysis_run_summary(body, compact=True)
    assert "items" not in compact["fit_failures"]


def test_fit_health_lists_failed_spectrum() -> None:
    from sersflow.api.services.fit_curve_export_runner import _failures_for_step, _health_csv_bytes

    run = SimpleNamespace(
        warnings_json=json.dumps(
            {
                "fit_failures": {
                    "items": [
                        {"spectrum_id": "sp_1", "step_id": "fit1", "step_index": 0, "status": "failed", "reason": "boom"},
                        {"spectrum_id": "sp_2", "step_id": "other", "step_index": 3, "status": "failed", "reason": "x"},
                    ]
                }
            }
        )
    )
    step = SimpleNamespace(step_id="fit1")
    fails = _failures_for_step(run, step, 0)
    assert fails == {"sp_1": "boom"}
    csv_text = _health_csv_bytes(
        [{"spectrum_id": "sp_1", "fit_status": "failed", "fit_failure_reason": "boom"}]
    ).decode()
    header, row = csv_text.strip().splitlines()
    assert header.startswith("spectrum_id,fit_status,fit_failure_reason")
    assert row.startswith("sp_1,failed,boom")
