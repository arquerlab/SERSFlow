"""Run safety / provenance: session+inline pipeline conflict, pipeline snapshots, fitting step numbering."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.infra.datasets_store import create_dataset
from sersflow.infra.sessions_store import create_session, update_session_pipeline  # noqa: F401


def _probe_pipeline(target: float = 200.0, pid: str = "p1") -> Pipeline:
    return Pipeline(
        steps=[
            PipelineStep(
                name="spectral_intensities",
                params={
                    "probes": [
                        {
                            "id": pid,
                            "target_cm1": target,
                            "acquisition": "fixed",
                            "method": "nearest",
                            "extrapolation": "nan",
                        }
                    ]
                },
            )
        ]
    )


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir()
    (tmp_path / "b1" / "s.txt").write_text("wn\tint\n100\t1\n200\t5\n300\t2\n", encoding="utf-8")
    ds = create_dataset(
        owner_user_id="dev",
        metadata=DatasetMetadata(name="t"),
        spectra=[SpectrumRef(spectrum_id="sp_1", relative_path="b1/s.txt", record_index=None)],
    )
    sess = create_session(dataset_id=ds.dataset_id, pipeline=_probe_pipeline(), subset=SubsetStrategy(kind="all"))
    return TestClient(app), ds, sess


def test_session_plus_inline_pipeline_is_rejected(env) -> None:
    client, ds, sess = env
    r = client.post(
        "/analysis/runs",
        json={
            "dataset_id": ds.dataset_id,
            "session_id": sess.session_id,
            "pipeline": _probe_pipeline(999.0, "other").model_dump(),
            "subset": {"kind": "all"},
        },
    )
    assert r.status_code == 400
    assert "not both" in r.json()["detail"]


def test_session_run_stores_pipeline_snapshot_and_is_exposed(env) -> None:
    client, ds, sess = env
    r = client.post("/analysis/runs", json={"dataset_id": ds.dataset_id, "session_id": sess.session_id})
    assert r.status_code in (200, 202), r.text
    run_id = r.json()["run_id"]
    assert r.json()["warnings"] == []

    # Edit the session pipeline afterwards; the run must keep reporting what it ran.
    update_session_pipeline(sess.session_id, _probe_pipeline(999.0, "p_live"))

    d = client.get(f"/analysis/runs/{run_id}/pipeline")
    assert d.status_code == 200
    body = d.json()
    assert body["snapshot"] is True
    probe_ids = [p["id"] for p in body["pipeline"]["steps"][0]["params"]["probes"]]
    assert probe_ids == ["p1"]
    assert body["pipeline_hash"]

    detail = client.get(f"/analysis/runs/{run_id}").json()["run"]
    assert detail["pipeline_hash"] == body["pipeline_hash"]


def _fitting_pipeline() -> Pipeline:
    comps = [
        {"component_id": "bg", "component_type": "shirley_bg"},
        {"component_id": "p1", "component_type": "gaussian"},
    ]
    step = lambda region: PipelineStep(  # noqa: E731
        name="fitting",
        params={
            "components": comps,
            "p0": [0.01, 0.0, 200.0, 4.0, 30.0],
            "bounds_lower": [0.0, None, 150.0, 0.0, 1.0],
            "bounds_upper": [0.1, None, 250.0, None, 80.0],
            "vary": [True, True, True, True, True],
            "technique_family": "xps",
            "xps_region": region,
        },
    )
    return Pipeline(steps=[PipelineStep(name="crop", params={"min_x": 50.0, "max_x": 350.0}), step("O1s"), step("C1s")],
                    technique_family="xps")


def test_fitting_steps_expose_column_prefix_and_both_numberings(env, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ds, _sess = env
    ds = create_dataset(
        owner_user_id="dev",
        metadata=DatasetMetadata(name="x", technique_family="xps"),
        spectra=[SpectrumRef(spectrum_id="sp_1", relative_path="b1/s.txt", record_index=None)],
    )
    sess = create_session(dataset_id=ds.dataset_id, pipeline=_fitting_pipeline(), subset=SubsetStrategy(kind="all"))
    r = client.post("/analysis/runs", json={"dataset_id": ds.dataset_id, "session_id": sess.session_id})
    assert r.status_code in (200, 202), r.text
    run_id = r.json()["run_id"]
    items = client.get(f"/analysis/runs/{run_id}/fitting-steps").json()["items"]
    assert [(i["step_index"], i["step_num"], i["column_prefix"]) for i in items] == [(1, 2, "s1_"), (2, 3, "s2_")]

    # step_index and step_num resolve to the same step; bad numbers return the valid choices.
    ok_num = client.post(f"/analysis/runs/{run_id}/fit-curve-jobs", json={"fitting_step_num": 3, "format": "csv"})
    ok_idx = client.post(f"/analysis/runs/{run_id}/fit-curve-jobs", json={"fitting_step_index": 2, "format": "csv"})
    assert ok_num.status_code == 202 and ok_idx.status_code == 202
    bad = client.post(f"/analysis/runs/{run_id}/fit-curve-jobs", json={"fitting_step_num": 1})
    assert bad.status_code == 400 and "valid step_nums: [2, 3]" in bad.json()["detail"]
    both = client.post(f"/analysis/runs/{run_id}/fit-curve-jobs", json={"fitting_step_num": 2, "fitting_step_index": 1})
    assert both.status_code == 400
    none = client.post(f"/analysis/runs/{run_id}/fit-curve-jobs", json={})
    assert none.status_code == 400
    _ = np  # keep import for parity with sibling tests


def _xps_fit_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Completed run with one Shirley+Gaussian fitting step (true FWHM = 2*sqrt(2 ln 2)*1.5 = 3.53 eV)."""
    pytest.importorskip("lmfitxps")
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir()
    rng = np.random.default_rng(2)
    x = np.linspace(300.0, 280.0, 200)
    y = 10.0 + 200.0 * np.exp(-((x - 290.0) ** 2) / (2 * 1.5**2)) + rng.normal(0.0, 1.0, x.size)
    (tmp_path / "b1" / "s.txt").write_text(
        "be" + chr(9) + "int" + chr(10) + chr(10).join(f"{a}{chr(9)}{b}" for a, b in zip(x, y)) + chr(10), encoding="utf-8"
    )
    ds = create_dataset(
        owner_user_id="dev",
        metadata=DatasetMetadata(name="fit", technique_family="xps"),
        spectra=[SpectrumRef(spectrum_id="sp_1", relative_path="b1/s.txt", record_index=None)],
    )
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "components": [
                        {"component_id": "bg", "component_type": "shirley_bg"},
                        {"component_id": "p1", "component_type": "gaussian"},
                    ],
                    "p0": [0.001, 0.0, 290.0, 150.0, 3.0],
                    "bounds_lower": [0.0, None, 285.0, 0.0, 0.5],
                    "bounds_upper": [0.01, None, 295.0, None, 8.0],
                    "vary": [True, True, True, True, True],
                    "fit_min_x": 284.0,
                    "fit_max_x": 296.0,
                    "technique_family": "xps",
                },
            )
        ],
        technique_family="xps",
    )
    sess = create_session(dataset_id=ds.dataset_id, pipeline=pipe, subset=SubsetStrategy(kind="all"))
    client = TestClient(app)
    r = client.post("/analysis/runs", json={"dataset_id": ds.dataset_id, "session_id": sess.session_id})
    assert r.status_code in (200, 202), r.text
    run_id = r.json()["run_id"]
    assert client.get(f"/analysis/runs/{run_id}").json()["run"]["status"] == "completed"
    return client, run_id


def test_fitting_preview_is_json_safe_with_window_and_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """NaN outside the fit window / unstored SSR used to turn the preview into an anonymous HTTP 500."""
    client, run_id = _xps_fit_run(tmp_path, monkeypatch)
    for kw in ({"fitting_step_num": 1}, {"fitting_step_index": 0}):
        p = client.post(
            f"/analysis/runs/{run_id}/fitting-preview",
            json={"spectrum_ids": ["sp_1"], "return_curve": True, **kw},
        )
        assert p.status_code == 200, p.text  # was HTTP 500 (NaN outside the window / ssr)
        item = p.json()["items"][0]
        assert item["error"] is None, item
        assert None in item["y_hat"]  # outside-window points are null, not NaN
        d = item["diagnostics"]
        assert d["ssr"] is None or isinstance(d["ssr"], float)
        for k in ("n_at_bound", "bg_gt_data_frac", "resid_mean_edge_lo", "resid_mean_edge_hi", "resid_lag1_autocorr"):
            assert k in d
        assert d["resid_lag1_autocorr"] is not None


def _wait_job(client: TestClient, job_id: str, timeout_s: float = 90.0) -> dict:
    import time

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        j = client.get(f"/analysis/fit-curve-jobs/{job_id}").json()
        if j["status"] in ("completed", "failed"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_sweep_job_finds_the_true_fwhm_and_reports_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import csv
    import io
    import zipfile

    client, run_id = _xps_fit_run(tmp_path, monkeypatch)
    r = client.post(
        f"/analysis/runs/{run_id}/sweep-jobs",
        json={"fitting_step_index": 0, "grid": [{"component_id": "p1", "key": "fwhm", "values": [1.5, 3.5, 6.0]}]},
    )
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"])
    assert job["status"] == "completed", job
    assert job["content"] == "sweep"
    dl = client.get(f"/analysis/fit-curve-jobs/{job['job_id']}/download")
    assert dl.status_code == 200 and "sweep_" in dl.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    assert set(zf.namelist()) == {"sweep_summary.csv", "sweep_points.csv"}
    summary = list(csv.DictReader(io.StringIO(zf.read("sweep_summary.csv").decode())))
    assert len(summary) == 3
    assert float(summary[0]["p1.fwhm"]) == pytest.approx(3.5)  # sorted by mean rmse: true FWHM first
    assert float(summary[0]["rmse_mean"]) < float(summary[-1]["rmse_mean"])
    for col in ("resid_lag1_autocorr_mean", "bg_gt_data_frac_mean", "resid_mean_edge_hi_mean", "n_at_bound_total"):
        assert col in summary[0]
    points = list(csv.DictReader(io.StringIO(zf.read("sweep_points.csv").decode())))
    assert len(points) == 3 and all(p["spectrum_id"] == "sp_1" and not p["error"] for p in points)
    assert float(points[1]["p:p1.fwhm"]) == pytest.approx(3.5)  # fixed value is what the fit used


def test_sweep_job_validates_grid_and_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, run_id = _xps_fit_run(tmp_path, monkeypatch)
    url = f"/analysis/runs/{run_id}/sweep-jobs"
    bad_comp = client.post(url, json={"fitting_step_index": 0, "grid": [{"component_id": "nope", "key": "fwhm", "values": [1.0]}]})
    assert bad_comp.status_code == 400 and "unknown component_id" in bad_comp.json()["detail"]
    bad_key = client.post(url, json={"fitting_step_index": 0, "grid": [{"component_id": "p1", "key": "zzz", "values": [1.0]}]})
    assert bad_key.status_code == 400 and "no parameter" in bad_key.json()["detail"]
    no_step = client.post(url, json={"grid": [{"component_id": "p1", "key": "fwhm", "values": [1.0]}]})
    assert no_step.status_code == 400
    bad_step = client.post(url, json={"fitting_step_num": 9, "grid": [{"component_id": "p1", "key": "fwhm", "values": [1.0]}]})
    assert bad_step.status_code == 400
