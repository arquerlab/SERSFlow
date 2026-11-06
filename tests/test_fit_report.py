"""R1: publication fit report (HTML + Markdown + JSON) for a Co 2p run."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pytest

from sersflow.core.report.fit_report_model import (
    casaxps_lineshape,
    link_relation_text,
    parameter_status,
    status_text,
)

pytest.importorskip("lmfitxps")


def test_lineshape_strings_and_constraint_text() -> None:
    assert casaxps_lineshape("gl", {"m": 30.0}) == "GL(30)"
    assert casaxps_lineshape("sgl", {"m": 70.0}) == "SGL(70)"
    assert casaxps_lineshape("gaussian", {}) == "GL(0)"
    assert casaxps_lineshape("la", {"alpha": 1.1, "beta": 9.0, "fwhm_g": 0.0}) == "LA(1.1,9)"
    assert "convolved" in casaxps_lineshape("gl_gauss", {"m": 30.0, "fwhm_g": 0.4})
    assert link_relation_text({"mode": "offset", "target_component_id": "A", "target_key": "pos", "offset": -1.6}) == "= A.pos - 1.6"
    assert link_relation_text({"mode": "area_ratio", "target_component_id": "A", "ratio": 0.5}) == "area = 0.5 x area(A)"
    assert link_relation_text({"mode": "expr", "expr": "{A.pos}+1"}) == "= {A.pos}+1"
    assert link_relation_text({"mode": "expr", "expr": "0.3*{A.area}", "defines": "area"}) == "area = 0.3*{A.area}"
    assert parameter_status(vary=False, lower=0.0, upper=1.0, link=None)["status"] == "fixed"
    assert status_text(parameter_status(vary=True, lower=778.0, upper=None, link=None)) == "bounded [778, +inf]"
    assert parameter_status(vary=True, lower=None, upper=None, link=None)["status"] == "free"


def _co2p_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from sersflow.api.main import app
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
    from sersflow.api.schemas.sessions import SubsetStrategy
    from sersflow.core.preprocess.fitting_specs import build_component_function, component_param_specs
    from sersflow.core.xps.recipe_apply import apply_recipe_id
    from sersflow.infra.datasets_store import create_dataset
    from sersflow.infra.sessions_store import create_session
    from tests.test_vamas_iso import _block, _header, _write

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"

    fit = apply_recipe_id("co_2p32_coo", pass_energy=20)
    fit.pop("xps_region", None)
    fit.pop("warnings", None)
    # synthetic counts from the recipe's seeded model (x = BE descending, as in the file)
    x = 795.0 - 0.1 * np.arange(231)
    y = np.full_like(x, 300.0)
    cur = 0
    for c in fit["components"]:
        n = len(component_param_specs(c["component_type"]))
        if c["component_type"] != "shirley_bg":
            f, _specs = build_component_function(c["component_type"])
            vals = list(fit["p0"][cur : cur + n])
            vals[1] = max(vals[1], 0.05) * 4000.0  # amp
            y = y + f(x, *vals)
        cur += n
    y = np.random.default_rng(5).poisson(np.clip(y, 1, None)).astype(float)
    (tmp_path / "b1").mkdir()
    _write(tmp_path / "b1", _header(n_blocks=1) + _block(x_start=795.0, x_step=-0.1, columns=[list(y)]), name="co.vms")
    ds = create_dataset(
        owner_user_id="dev",
        metadata=DatasetMetadata(name="co2p", technique_family="xps"),
        spectra=[SpectrumRef(spectrum_id="sp_co", relative_path="b1/co.vms", record_index=0)],
    )
    fit.update({"technique_family": "xps", "fit_min_x": 772.5, "fit_max_x": 794.0})
    pipe = Pipeline(
        steps=[
            PipelineStep(name="x_axis_calibration", params={"method": "fixed_offset", "offset": 0.3}),
            PipelineStep(name="fitting", params=fit),
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


def test_co2p_report_has_every_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gap doc R1 'done when': a Co 2p run's report contains every required item, via REST (zip + JSON)."""
    from test_run_provenance_api import _wait_job

    client, run_id = _co2p_run(tmp_path, monkeypatch)
    r = client.post(f"/analysis/runs/{run_id}/report-jobs", json={})
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"], timeout_s=180)
    assert job["status"] == "completed", job
    rep = client.get(f"/analysis/report-jobs/{job['job_id']}/json").json()

    missing = [c["item"] for c in rep["checklist"] if not c["present"]]
    assert missing == [], missing
    assert rep["software"]["version"] and rep["run"]["pipeline_hash"]
    s = rep["spectra"][0]
    assert len(s["file"]["sha256"]) == 64
    acq = s["acquisition"]
    assert acq["excitation_energy_eV"] == pytest.approx(1486.6) and acq["pass_energy_eV"] == 20.0
    assert acq["x_step_eV"] == pytest.approx(0.1) and acq["dwell_time_s"] == 0.1 and acq["n_scans"] == 5
    assert acq["max_channel_counts"] > 0 and acq["max_channel_cps"] == pytest.approx(acq["max_channel_counts"] / 0.5)
    assert acq["source_analyser_angle_deg"] == pytest.approx(54.7)
    assert s["charge_shift_eV"] == {"1": pytest.approx(0.3)}
    assert rep["charge_correction"]["steps"][0]["method"] == "fixed_offset"
    assert rep["quantification"]["status"] == "not_performed"

    f = s["fits"][0]
    assert f["background"]["component_type"] == "shirley_bg"
    comps = {c["component_id"]: c for c in f["components"]}
    assert all(c["lineshape"].startswith("GL(") for c in comps.values())
    assert sum(c["area_pct"] for c in comps.values()) == pytest.approx(100.0)
    statuses = {p["status"] for c in comps.values() for p in c["params"].values()}
    assert {"fixed", "linked"} <= statuses  # recipe widths fixed, satellite / offsets linked
    linked = [p["relation"] for c in comps.values() for p in c["params"].values() if p["status"] == "linked"]
    assert any(rel.startswith("area = ") for rel in linked) and any(".pos +" in rel for rel in linked)
    st = f["statistics"]
    assert st["n_points"] > 100 and st["n_vary"] >= 2 and st["redchi"] is not None
    assert "Levenberg-Marquardt" in st["optimiser"] and st["residual_std_normalised"] is not None

    dl = client.get(f"/analysis/fit-curve-jobs/{job['job_id']}/download")
    assert dl.status_code == 200 and "fit_report_" in dl.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    names = set(zf.namelist())
    assert {"report.html", "report.md", "report.json"} <= names and f["figure"] in names
    html = zf.read("report.html").decode()
    assert "data:image/png;base64," in html and "SHA-256" in html and "not part of this report" in html
    md = zf.read("report.md").decode()
    assert f"]({f['figure']})" in md and "| Peak | Line shape |" in md
    assert json.loads(zf.read("report.json")) == rep


def test_report_job_rejects_unknown_and_unfinished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_run_provenance_api import _wait_job, _xps_fit_run

    client, run_id = _xps_fit_run(tmp_path, monkeypatch)
    assert client.get("/analysis/report-jobs/fcjob_nope/json").status_code == 404
    r = client.post(f"/analysis/runs/{run_id}/report-jobs", json={"fitting_step_nums": [9]})
    job = _wait_job(client, r.json()["job_id"])
    assert job["status"] == "failed" and "fitting step" in job["error"]
    ok = _wait_job(client, client.post(f"/analysis/runs/{run_id}/report-jobs", json={"include_figures": False}).json()["job_id"])
    rep = client.get(f"/analysis/report-jobs/{ok['job_id']}/json").json()
    # plain-text spectrum: provenance and fit are complete, VAMAS acquisition items are flagged as missing
    missing = {c["item"] for c in rep["checklist"] if not c["present"]}
    assert missing == {"acquisition", "max_channel"}
