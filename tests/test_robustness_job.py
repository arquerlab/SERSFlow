"""Robustness study job end to end: plan, run (serial and parallel), resume, reanalyse, caps, upstream factors."""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("lmfitxps")

from sersflow.api.main import app  # noqa: E402
from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef  # noqa: E402
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep  # noqa: E402
from sersflow.api.schemas.sessions import SubsetStrategy  # noqa: E402
from sersflow.infra.analysis_store import get_fit_curve_job, update_fit_curve_job  # noqa: E402
from sersflow.infra.datasets_store import create_dataset  # noqa: E402
from sersflow.infra.sessions_store import create_session  # noqa: E402

from test_run_provenance_api import _wait_job  # noqa: E402

FRACS = (0.25, 0.40, 0.55)


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, baseline_step: bool = False):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir()
    x = np.linspace(300.0, 280.0, 241)
    refs = []
    for i, frac in enumerate(FRACS):
        rng = np.random.default_rng(i)
        sa = 1.3 / 2.355 * 2.0
        a = 150.0 * (1 - frac) * np.exp(-((x - 290.0) ** 2) / (2 * 1.4**2))
        b = 150.0 * frac * np.exp(-((x - 291.8) ** 2) / (2 * 1.4**2))
        cum = np.cumsum((a + b)[::-1])[::-1]
        y = 20.0 + 10.0 * cum / cum[0] + a + b + rng.normal(0.0, 1.0, x.size)
        p = tmp_path / "b1" / f"s{i}.txt"
        p.write_text("be\tint\n" + "\n".join(f"{u}\t{v}" for u, v in zip(x, y)) + "\n", encoding="utf-8")
        refs.append(SpectrumRef(spectrum_id=f"sp_{i}", relative_path=f"b1/s{i}.txt", record_index=None))
    ds = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="rb", technique_family="xps"), spectra=refs)
    fit = PipelineStep(
        name="fitting",
        params={
            "components": [
                {"component_id": "bg", "component_type": "shirley_bg"},
                {"component_id": "A", "component_type": "gaussian"},
                {"component_id": "B", "component_type": "gaussian"},
            ],
            "p0": [0.001, 0.0, 290.0, 100.0, 3.3, 291.8, 60.0, 3.3],
            "bounds_lower": [0.0, None, 289.0, 0.0, 0.5, 291.0, 0.0, 0.5],
            "bounds_upper": [0.01, None, 291.0, None, 8.0, 293.0, None, 8.0],
            "vary": [True] * 8,
            "fit_min_x": 284.0,
            "fit_max_x": 296.0,
            "technique_family": "xps",
        },
    )
    steps = ([PipelineStep(name="baseline", params={"method": "linear"})] if baseline_step else []) + [fit]
    pipe = Pipeline(steps=steps, technique_family="xps")
    sess = create_session(dataset_id=ds.dataset_id, pipeline=pipe, subset=SubsetStrategy(kind="all"))
    client = TestClient(app)
    r = client.post("/analysis/runs", json={"dataset_id": ds.dataset_id, "session_id": sess.session_id})
    assert r.status_code in (200, 202), r.text
    run_id = r.json()["run_id"]
    assert client.get(f"/analysis/runs/{run_id}").json()["run"]["status"] == "completed"
    return client, run_id, (1 if baseline_step else 0)


FACTORS = [
    {"name": "background", "levels": [
        {"name": "shirley", "patches": []},
        {"name": "linear", "patches": [{"op": "swap_component_type", "select": {"component_ids": ["bg"]}, "new_type": "linear_bg"}]},
    ]},
    {"name": "window", "levels": [
        {"name": "wide", "patches": []},
        {"name": "narrow", "patches": [
            {"op": "set_step_param", "key": "fit_min_x", "value": 285.5},
            {"op": "set_step_param", "key": "fit_max_x", "value": 295.0},
        ]},
    ]},
    {"name": "fwhm", "levels": [
        {"name": "free", "patches": []},
        {"name": "tied", "patches": [{"op": "tie_param", "select": {"role": "peaks"}, "key": "fwhm"}]},
    ]},
]
RESPONSES = [
    {"name": "B_pct", "kind": "area_pct", "component_id": "B"},
    {"name": "B_frac", "kind": "group_fraction", "numerator": ["B"], "denominator": ["A", "B"]},
]


def _body(idx: int, **kw):
    return {"fitting_step_index": idx, "factors": FACTORS, "responses": RESPONSES, "workers": 1, **kw}


def _download(client, job_id):
    dl = client.get(f"/analysis/fit-curve-jobs/{job_id}/download")
    assert dl.status_code == 200 and "robustness_" in dl.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(dl.content))


def _points(zf):
    rows = list(csv.DictReader(io.StringIO(zf.read("variant_points.csv").decode())))
    return {(r["spectrum_id"], r["cell_id"]): r for r in rows}


def test_plan_preset_and_cost(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    r = client.post(
        f"/analysis/runs/{run_id}/robustness-plan",
        json={"fitting_step_index": idx, "preset": "fit_model_choices", "n_starts": 3, "noise": {"n_replicates": 20}},
    )
    assert r.status_code == 200, r.text
    plan = r.json()
    names = [f["name"] for f in plan["factors"]]
    assert names == ["background", "window", "fwhm_constraint"]  # gaussians: no mix factor
    assert [lv["name"] for lv in plan["factors"][0]["levels"]][0] == "shirley_bg"
    assert {r_["name"] for r_ in plan["responses"]} == {"A_area_pct", "B_area_pct"}
    est = plan["estimate"]
    assert est["n_cells"] == 3 * 3 * 2 and est["n_spectra"] == 3
    assert est["n_fits"] == 18 * 3 * 3 and est["n_noise_fits"] == 60
    assert est["exceeds_limit"] is False
    # explicit factors override the preset; a bad cap is a 400 with the cell count
    capped = client.post(f"/analysis/runs/{run_id}/robustness-plan", json=_body(idx, max_cells=4))
    assert capped.status_code == 400 and "max_cells" in capped.json()["detail"]
    bad_resp = client.post(f"/analysis/runs/{run_id}/robustness-plan", json={**_body(idx), "responses": [{"name": "x", "kind": "nope"}]})
    assert bad_resp.status_code == 400
    assert client.get("/analysis/robustness-presets").json()["presets"]


def test_job_runs_and_serial_equals_parallel(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    body = _body(idx, n_starts=2, seed=5, noise={"n_replicates": 12, "seed": 3}, filter={"mode": "delta_bic_common", "threshold": 1e6})
    r = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=body)
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"], timeout_s=240)
    assert job["status"] == "completed", job
    assert job["content"] == "robustness" and job["progress_done"] == job["progress_total"] == 8 * 3 + 3

    s = client.get(f"/analysis/robustness-jobs/{job['job_id']}/summary").json()
    assert s["design"]["n_cells"] == 8 and s["design"]["exact"] and s["meta"]["n_spectra"] == 3
    blk = s["responses"]["B_frac"]
    assert blk["anova"]["exact"] and blk["anova"]["n_spectra"] == 3
    terms = {t["term"]: t for t in blk["anova"]["terms"]}
    assert {"background", "window", "fwhm"} <= set(terms)
    assert sum(t["share_pooled"] for t in terms.values()) == pytest.approx(1.0, abs=1e-6)
    nc = blk["noise_comparison"]
    assert nc["n_spectra"] == 3 and nc["ratio_var_median"] > 0
    assert s["filter"]["n_kept"] == 24 and s["degeneracy"]["n_fits"] == 24

    zf = _download(client, job["job_id"])
    assert {"design.csv", "variant_points.csv", "anova.csv", "trend.csv", "bands.csv", "noise_comparison.csv",
            "filter_report.csv", "summary.json", "study_spec.json", "provenance.json", "robustness_records.jsonl"} <= set(zf.namelist())
    serial = _points(zf)
    assert len(serial) == 24 and all(not r_["error"] for r_ in serial.values())
    # the common-window score is present for every cell and shares one n_common
    assert len({r_["n_common"] for r_ in serial.values()}) == 1
    prov = json.loads(zf.read("provenance.json"))
    assert prov["design_hash"] == s["design"]["design_hash"]

    # parallel (2 worker processes) gives the same answer
    r2 = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json={**body, "workers": 2})
    job2 = _wait_job(client, r2.json()["job_id"], timeout_s=300)
    assert job2["status"] == "completed", job2
    par = _points(_download(client, job2["job_id"]))
    assert par.keys() == serial.keys()
    for k, row in serial.items():
        assert float(par[k]["B_frac"]) == pytest.approx(float(row["B_frac"]), rel=1e-9, abs=1e-12)
        assert par[k]["best_start"] == row["best_start"]

    # reanalyse: new response from the stored fits, tighter filter, main effects only; no refit
    ra = client.post(
        f"/analysis/robustness-jobs/{job['job_id']}/reanalyse",
        json={
            "responses": [{"name": "A_pct", "kind": "area_pct", "component_id": "A"}, {"name": "B_pos", "kind": "param", "component_id": "B", "key": "pos"}],
            "interaction_order": 1,
        },
    )
    assert ra.status_code == 200, ra.text
    rs = ra.json()
    assert set(rs["responses"]) == {"A_pct", "B_pos"}
    assert max(t["order"] for t in rs["responses"]["A_pct"]["anova"]["terms"]) <= 2  # main effects + 'higher-order'
    # a zero dBIC threshold keeps only the best cell of every spectrum (nothing left to decompose)
    tight = client.post(f"/analysis/robustness-jobs/{job['job_id']}/reanalyse", json={"filter": {"mode": "delta_bic_common", "threshold": 0.0}})
    assert tight.status_code == 200 and tight.json()["filter"]["n_kept"] == 3 and tight.json()["filter"]["n_removed"] == 21
    # A% and B% sum to 100 in every fit
    pa = {k: float(v) for k, v in ((k, row["B_pct"]) for k, row in serial.items())}
    assert all(0.0 < v < 100.0 for v in pa.values())


def test_resume_only_refits_missing_pairs(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    r = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=_body(idx, seed=1))
    job = _wait_job(client, r.json()["job_id"], timeout_s=240)
    assert job["status"] == "completed"
    full = _points(_download(client, job["job_id"]))
    rec = get_fit_curve_job(job["job_id"])
    jl = Path(rec.artifact_path).parent / "robustness_records.jsonl"
    lines = jl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 24
    keep = lines[:10]
    jl.write_text("\n".join(keep) + "\n{\"torn", encoding="utf-8")  # simulated crash, torn last line
    update_fit_curve_job(job_id=job["job_id"], status="failed", error="simulated", finished=True)
    rr = client.post(f"/analysis/robustness-jobs/{job['job_id']}/resume")
    assert rr.status_code == 202, rr.text
    job2 = _wait_job(client, job["job_id"], timeout_s=240)
    assert job2["status"] == "completed", job2
    again = _points(_download(client, job["job_id"]))
    assert again.keys() == full.keys()
    for k in full:
        assert float(again[k]["B_frac"]) == pytest.approx(float(full[k]["B_frac"]), rel=1e-9, abs=1e-12)
    assert client.post(f"/analysis/robustness-jobs/{job['job_id']}/resume").status_code == 409  # completed


def test_cap_blocks_unless_allow_large(tmp_path, monkeypatch):
    monkeypatch.setenv("SERSFLOW_ROBUSTNESS_MAX_FITS", "5")
    client, run_id, idx = _run(tmp_path, monkeypatch)
    plan = client.post(f"/analysis/runs/{run_id}/robustness-plan", json=_body(idx)).json()
    assert plan["estimate"]["exceeds_limit"] is True and plan["estimate"]["n_total_fits"] == 24
    r = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=_body(idx))
    job = _wait_job(client, r.json()["job_id"])
    assert job["status"] == "failed" and "SERSFLOW_ROBUSTNESS_MAX_FITS" in job["error"]
    ok = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=_body(idx, allow_large=True))
    assert _wait_job(client, ok.json()["job_id"], timeout_s=240)["status"] == "completed"


def test_upstream_factor_groups_cells_and_changes_prefit_spectra(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch, baseline_step=True)
    assert idx == 1
    factors = [
        {"name": "baseline", "levels": [
            {"name": "linear", "patches": []},
            {"name": "shirley", "patches": [{"op": "set_step_param", "target": {"step_name": "baseline"}, "key": "method", "value": "shirley"}]},
        ]},
        FACTORS[2],
    ]
    plan = client.post(f"/analysis/runs/{run_id}/robustness-plan", json={"fitting_step_index": idx, "factors": factors, "responses": RESPONSES}).json()
    assert plan["estimate"]["n_upstream_groups"] == 2
    r = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json={"fitting_step_index": idx, "factors": factors, "responses": RESPONSES, "workers": 1})
    job = _wait_job(client, r.json()["job_id"], timeout_s=240)
    assert job["status"] == "completed", job
    zf = _download(client, job["job_id"])
    pts = _points(zf)
    assert len(pts) == 4 * 3 and all(not v["error"] for v in pts.values())
    # same fit model, different upstream baseline -> different fitted values for the same spectrum
    a = pts[("sp_1", "c00000")]
    b = pts[("sp_1", "c00002")]
    assert (a["baseline"], b["baseline"]) == ("linear", "shirley") and a["fwhm"] == b["fwhm"]
    assert float(a["rmse"]) != pytest.approx(float(b["rmse"]))
    s = json.loads(zf.read("summary.json"))
    assert "baseline" in {t["term"] for t in s["responses"]["B_frac"]["anova"]["terms"]}


# ------------------------------------------------------------------ Co 2p-like example (recipe model)


def _spectrum_text(x, y) -> str:
    rows = [f"{u}{chr(9)}{v}" for u, v in zip(x, y)]
    return "be" + chr(9) + "int" + chr(10) + chr(10).join(rows) + chr(10)




def _co2p_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fracs=(0.15, 0.35, 0.55)):
    """Spectra generated from the Co3O4 recipe model (links, locked satellites), Co3+-like share varying."""
    from sersflow.core.preprocess.fitting import evaluate_fit_curves, fit_problem_from_step_params
    from sersflow.core.spectrum import XY
    from sersflow.core.xps.recipe_apply import apply_recipe_id

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir()
    step = apply_recipe_id("co_2p32_co3o4", pass_energy=20)
    step.pop("xps_region", None)
    for k in ("recipe_id", "recipe_pass_energy", "pass_energy_resolution", "warnings", "recipe_ids"):
        step.pop(k, None)
    step.update({"technique_family": "xps", "fit_min_x": 774.0, "fit_max_x": 792.0})
    amp_idx = [3, 8, 13]  # amp of peak_1..3 (bg: 2 params, then pos, amp, fwhm, m per GL peak)
    base_p = list(step["p0"])
    base_p[1] = 300.0  # Shirley const
    for i in range(5):
        base_p[2 + 4 * i + 1] *= 2500.0
    step["p0"] = base_p
    x = np.linspace(792.0, 774.0, 361)
    refs = []
    for i, frac in enumerate(fracs):
        p = list(base_p)
        p[amp_idx[0]] = base_p[amp_idx[0]] * (1.0 - frac) * 2.0  # peak_1 (Co3+-like)
        for j in (1, 2):
            p[amp_idx[j]] = base_p[amp_idx[j]] * (0.5 + frac)
        prob = fit_problem_from_step_params(XY(x=x, y=np.zeros_like(x)), {**step, "p0": p})
        y = np.asarray(evaluate_fit_curves(prob, np.asarray(p)).y_hat, dtype=float)
        y = y + np.random.default_rng(10 + i).normal(0.0, 8.0, x.size)
        f = tmp_path / "b1" / f"c{i}.txt"
        f.write_text(_spectrum_text(x, y), encoding="utf-8")
        refs.append(SpectrumRef(spectrum_id=f"sp_{i}", relative_path=f"b1/c{i}.txt", record_index=None))
    ds = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="co", technique_family="xps"), spectra=refs)
    pipe = Pipeline(steps=[PipelineStep(name="fitting", params=step)], technique_family="xps")
    sess = create_session(dataset_id=ds.dataset_id, pipeline=pipe, subset=SubsetStrategy(kind="all"))
    client = TestClient(app)
    r = client.post("/analysis/runs", json={"dataset_id": ds.dataset_id, "session_id": sess.session_id})
    assert r.status_code in (200, 202), r.text
    run_id = r.json()["run_id"]
    assert client.get(f"/analysis/runs/{run_id}").json()["run"]["status"] == "completed"
    return client, run_id


def test_co2p_recipe_preset_proposes_chemically_meaningful_factors_and_runs(tmp_path, monkeypatch):
    client, run_id = _co2p_run(tmp_path, monkeypatch)
    plan = client.post(
        f"/analysis/runs/{run_id}/robustness-plan", json={"fitting_step_index": 0, "preset": "fit_model_choices"}
    ).json()
    by = {f["name"]: [lv["name"] for lv in f["levels"]] for f in plan["factors"]}
    assert list(by) == ["background", "window", "lineshape_mix", "fwhm_constraint", "satellite_treatment"]
    assert by["background"][0] == "shirley_bg" and set(by["background"]) == {"shirley_bg", "tougaard_u4_bg", "linear_bg"}
    assert by["lineshape_mix"] == ["m=as_recipe", "m=20(fixed)", "m=40(fixed)"]
    assert by["fwhm_constraint"] == ["fixed_as_recipe", "free_pm30%"]
    assert by["satellite_treatment"] == ["locked_as_recipe", "unlocked", "absent"]
    assert plan["estimate"]["n_cells"] == 3 * 3 * 3 * 2 * 3 and {r_["name"] for r_ in plan["responses"]} >= {"peak_1_area_pct"}

    keep = {"background", "fwhm_constraint", "satellite_treatment"}
    factors = [f for f in plan["factors"] if f["name"] in keep]
    # Tougaard-U4 with locked satellites is a slow optimisation (10-25 s per fit): checked in the plan, not run here.
    factors[0]["levels"] = [lv for lv in factors[0]["levels"] if lv["name"] != "tougaard_u4_bg"]
    responses = [{"name": "main1_frac", "kind": "group_fraction", "numerator": ["peak_1"], "denominator": ["peak_1", "peak_2", "peak_3"]}]
    body = {"fitting_step_index": 0, "factors": factors, "responses": responses, "workers": 2, "n_starts": 2, "seed": 4,
            "filter": {"mode": "delta_bic_common", "threshold": 1e9}}
    r = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=body)
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"], timeout_s=420)
    assert job["status"] == "completed", job
    zf = _download(client, job["job_id"])
    pts = _points(zf)
    assert len(pts) == 2 * 2 * 3 * 3
    ok = [v for v in pts.values() if not v["error"]]
    assert len(ok) >= 0.9 * len(pts), [v["error"] for v in pts.values() if v["error"]][:3]
    # the absent-satellite cells have no satellite component but the responses (main peaks) still evaluate
    absent = [v for v in ok if v["satellite_treatment"] == "absent"]
    assert absent and all(v["main1_frac"] != "" for v in absent)
    s = json.loads(zf.read("summary.json"))
    terms = {t["term"]: t for t in s["responses"]["main1_frac"]["anova"]["terms"]}
    assert set(["background", "fwhm_constraint", "satellite_treatment"]) <= set(terms)
    assert sum(t["share_pooled"] for t in terms.values()) == pytest.approx(1.0, abs=1e-6)
    # the response really follows the generated truth: Co3+-like share falls as frac rises
    means = {}
    for (sid, _c), v in pts.items():
        if v["main1_frac"] != "":
            means.setdefault(sid, []).append(float(v["main1_frac"]))
    mu = [float(np.mean(means[f"sp_{i}"])) for i in range(3)]
    assert mu[0] > mu[1] > mu[2]


# ------------------------------------------------------------------ vibrational (SERS-like): same engine, other technique


def _vib_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir()
    x = np.linspace(500.0, 1500.0, 400)
    refs = []
    for i, share in enumerate((0.3, 0.5, 0.7)):
        rng = np.random.default_rng(20 + i)
        lor = lambda pos, a, w: a * (w / 2) ** 2 / ((x - pos) ** 2 + (w / 2) ** 2)  # noqa: E731
        y = 200.0 + 0.1 * (x - 500.0) + 40.0 * np.exp(-((x - 900.0) / 500.0) ** 2) + lor(800.0, 100.0 * (1 - share), 30.0) + lor(1000.0, 100.0 * share, 30.0)
        y = y + rng.normal(0.0, 0.8, x.size)
        (tmp_path / "b1" / f"v{i}.txt").write_text(_spectrum_text(x, y), encoding="utf-8")
        refs.append(SpectrumRef(spectrum_id=f"sp_{i}", relative_path=f"b1/v{i}.txt", record_index=None))
    ds = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="vib", technique_family="vibrational"), spectra=refs)
    fit = PipelineStep(
        name="fitting",
        params={
            "components": [
                {"component_id": "A", "component_type": "lorentzian"},
                {"component_id": "B", "component_type": "lorentzian"},
                {"component_id": "bg", "component_type": "polynomial_background", "degree": 1},
            ],
            "p0": [800.0, 60.0, 30.0, 1000.0, 40.0, 30.0, 0.0, 0.0],
            "bounds_lower": [780.0, 0.0, 5.0, 980.0, 0.0, 5.0, None, None],
            "bounds_upper": [820.0, None, 80.0, 1020.0, None, 80.0, None, None],
            "vary": [True] * 8,
            "technique_family": "vibrational",
        },
    )
    pipe = Pipeline(steps=[PipelineStep(name="baseline", params={"method": "asls"}), fit], technique_family="vibrational")
    sess = create_session(dataset_id=ds.dataset_id, pipeline=pipe, subset=SubsetStrategy(kind="all"))
    client = TestClient(app)
    r = client.post("/analysis/runs", json={"dataset_id": ds.dataset_id, "session_id": sess.session_id})
    assert r.status_code in (200, 202), r.text
    run_id = r.json()["run_id"]
    assert client.get(f"/analysis/runs/{run_id}").json()["run"]["status"] == "completed"
    return client, run_id


def test_vibrational_baseline_method_factor_runs_through_the_same_engine(tmp_path, monkeypatch):
    pytest.importorskip("pybaselines")
    client, run_id = _vib_run(tmp_path, monkeypatch)
    plan = client.post(
        f"/analysis/runs/{run_id}/robustness-plan",
        json={"fitting_step_index": 1, "preset": "baseline_method", "preset_options": {"methods": ["asls", "arpls", "modpoly"]}},
    ).json()
    assert [f["name"] for f in plan["factors"]] == ["baseline_method"]
    assert [lv["name"] for lv in plan["factors"][0]["levels"]] == ["asls", "arpls", "modpoly"]  # nominal first
    assert plan["estimate"]["n_upstream_groups"] == 3 and {r_["name"] for r_ in plan["responses"]} == {"A_area_pct", "B_area_pct"}
    # the fit-model preset on a vibrational step offers polynomial backgrounds, not XPS ones
    fm = client.post(f"/analysis/runs/{run_id}/robustness-plan", json={"fitting_step_index": 1, "preset": "fit_model_choices"}).json()
    bgf = next(f for f in fm["factors"] if f["name"] == "background")
    assert [lv["name"] for lv in bgf["levels"]] == ["polynomial_background_deg1", "polynomial_deg2", "polynomial_deg3"]

    # both factors together: 3 baselines x 3 polynomial degrees
    factors = plan["factors"] + [bgf]
    r = client.post(
        f"/analysis/runs/{run_id}/robustness-jobs",
        json={"fitting_step_index": 1, "factors": factors, "responses": plan["responses"], "workers": 1},
    )
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"], timeout_s=300)
    assert job["status"] == "completed", job
    zf = _download(client, job["job_id"])
    pts = _points(zf)
    assert len(pts) == 9 * 3
    assert all(not v["error"] for v in pts.values()), [v["error"] for v in pts.values() if v["error"]][:2]
    s = json.loads(zf.read("summary.json"))
    terms = {t["term"] for t in s["responses"]["B_area_pct"]["anova"]["terms"]}
    assert {"baseline_method", "background"} <= terms
    b_pct = [float(v["B_area_pct"]) for v in pts.values()]
    assert 30.0 < float(np.mean(b_pct)) < 70.0  # peaks recovered, whatever the baseline
