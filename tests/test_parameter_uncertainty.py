"""F2: per-parameter covariance errors, area / %area errors, Monte Carlo uncertainties (core, export, REST jobs)."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import numpy as np
import pytest

from sersflow.core.metrics.fit_uncertainty import area_uncertainty, component_uncertainty_rows, run_monte_carlo
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params

pytest.importorskip("lmfit")

from test_poisson_weighting import _params, _poisson_xy  # noqa: E402


def _fit(seed: int, params: dict | None = None):
    prob = fit_problem_from_step_params(_poisson_xy(seed), params or _params())
    return prob, fit_curve(prob)


def test_covariance_errors_match_the_empirical_scatter_of_independent_spectra() -> None:
    _prob, res = _fit(0)
    unc = area_uncertainty(res.mapping, res.p_opt, res.p_cov)
    ps, pct = [], []
    for s in range(1, 41):
        _p, r = _fit(s)
        ps.append(r.p_opt)
        pct.append(area_uncertainty(r.mapping, r.p_opt, r.p_cov).area_pct[0])
    emp = np.std(np.asarray(ps), axis=0, ddof=1)
    free = [0, 1, 2, 4, 5, 6, 8]  # m of both peaks is fixed
    # 40 replicates: the empirical SD itself scatters by ~11 %; allow 35 %
    np.testing.assert_allclose(res.p_stderr[free], emp[free], rtol=0.35)
    assert np.isnan(res.p_stderr[3]) and np.isnan(res.p_stderr[7])  # fixed -> no error
    assert unc.area_pct_stderr[0] == pytest.approx(np.std(pct, ddof=1), rel=0.35)
    assert unc.area_pct[0] + unc.area_pct[1] == pytest.approx(100.0)
    assert unc.area_pct_stderr[0] == pytest.approx(unc.area_pct_stderr[1])  # two peaks: same error
    assert unc.area[2] is None and unc.area_pct[2] is None  # background has no area


def test_linked_parameter_error_is_propagated_through_the_expression() -> None:
    p = _params()
    p["param_links"] = [
        {"source_component_id": "b", "source_key": "fwhm", "target_component_id": "a", "target_key": "fwhm", "mode": "scale", "scale": 1.375}
    ]
    _prob, res = _fit(3, p)
    assert res.p_stderr[6] == pytest.approx(1.375 * res.p_stderr[2], rel=1e-4)
    rows = component_uncertainty_rows(res)
    assert rows[1]["stderr"]["fwhm"] == pytest.approx(res.p_stderr[6])
    assert rows[0]["stderr"]["m"] is None


def test_monte_carlo_sd_agrees_with_empirical_scatter_and_covariance() -> None:
    prob, res = _fit(0)
    mc = run_monte_carlo(prob, res, n_replicates=60, seed=11)
    assert mc.n_ok == 60 and "Poisson" in mc.noise_model
    sd = np.std(mc.params, axis=0, ddof=1)
    emp = np.std(np.asarray([_fit(s)[1].p_opt for s in range(1, 41)]), axis=0, ddof=1)
    for i in (0, 1, 2, 4, 5, 6, 8):
        assert sd[i] == pytest.approx(emp[i], rel=0.4)
        assert sd[i] == pytest.approx(res.p_stderr[i], rel=0.4)
    assert np.all(sd[[3, 7]] == 0.0)  # fixed parameters do not move
    assert np.allclose(np.nansum(mc.area_pct, axis=1), 100.0)


def test_monte_carlo_is_reproducible_and_handles_shirley_and_relative_poisson() -> None:
    from test_poisson_weighting import X  # noqa: F401

    xy = _poisson_xy(4, scale=0.37)  # non-integer counts -> relative Poisson
    p = _params()
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    bg = component_param_specs("shirley_bg")
    p["components"] = [{"component_id": "bg", "component_type": "shirley_bg"}, *p["components"][:2]]
    p["p0"] = [s.default if s.default is not None else 0.0 for s in bg] + p["p0"][:8]
    p["bounds_lower"] = [s.lower_default for s in bg] + p["bounds_lower"][:8]
    p["bounds_upper"] = [s.upper_default for s in bg] + p["bounds_upper"][:8]
    p["vary"] = [True] * len(bg) + p["vary"][:8]
    prob = fit_problem_from_step_params(xy, p)
    res = fit_curve(prob)
    a = run_monte_carlo(prob, res, n_replicates=5, seed=3)
    b = run_monte_carlo(prob, res, n_replicates=5, seed=3)
    assert "relative Poisson" in a.noise_model
    assert a.n_ok == 5 and np.allclose(a.params, b.params)


def test_observation_columns_carry_errors_and_keep_the_parameter_layout() -> None:
    from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
    from sersflow.core.metrics.fitting_features import (
        collect_fitting_features_for_pipeline,
        p_opt_and_gof_from_features,
        stored_component_uncertainty_rows,
    )

    pipe = Pipeline(steps=[PipelineStep(name="fitting", params=_params())], technique_family="xps")
    keys, vals = collect_fitting_features_for_pipeline(_poisson_xy(6), pipe)
    for k in ("fit_a_area_pct", "fit_a_pos_stderr", "fit_a_area_stderr", "fit_a_area_pct_stderr", "fit_bg_c0_stderr"):
        assert k in keys and vals[k] is not None and np.isfinite(vals[k]), k
    assert vals["fit_a_m_stderr"] is None  # fixed
    assert vals["fit_a_area_pct"] + vals["fit_b_area_pct"] == pytest.approx(100.0)
    p_opt, _diag, err = p_opt_and_gof_from_features(pipeline=pipe, fitting_step_num=1, features=vals)
    assert err is None and p_opt[0] == pytest.approx(vals["fit_a_pos"])
    rows = stored_component_uncertainty_rows(pipeline=pipe, fitting_step_num=1, features=vals)
    assert rows[0]["stderr"]["pos"] == pytest.approx(vals["fit_a_pos_stderr"])
    assert rows[1]["area_pct"] == pytest.approx(vals["fit_b_area_pct"])
    assert rows[2]["area"] is None and rows[2]["stderr"]["c0"] == pytest.approx(vals["fit_bg_c0_stderr"])


def test_monte_carlo_job_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_run_provenance_api import _wait_job, _xps_fit_run

    client, run_id = _xps_fit_run(tmp_path, monkeypatch)
    prev = client.post(
        f"/analysis/runs/{run_id}/fitting-preview", json={"spectrum_ids": ["sp_1"], "fitting_step_index": 0}
    ).json()["items"][0]
    p1 = next(c for c in prev["components"] if c["component_id"] == "p1")
    assert p1["stderr"]["fwhm"] > 0 and p1["area_pct"] == pytest.approx(100.0)

    r = client.post(f"/analysis/runs/{run_id}/monte-carlo-jobs", json={"fitting_step_index": 0, "n_replicates": 20, "seed": 1})
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"])
    assert job["status"] == "completed", job
    assert job["content"] == "monte_carlo" and job["progress_done"] == 20
    s = client.get(f"/analysis/monte-carlo-jobs/{job['job_id']}/summary").json()
    assert s["n_replicates"] == 20 and s["spectra"][0]["error"] is None
    row = next(x for x in s["rows"] if x["component_id"] == "p1" and x["quantity"] == "fwhm")
    assert row["n_ok"] == 20 and row["mc_sd"] > 0
    assert row["mc_sd"] == pytest.approx(row["stderr_cov"], rel=0.6)  # 20 replicates: loose
    assert row["mc_p2_5"] < row["best_fit"] < row["mc_p97_5"]
    dl = client.get(f"/analysis/fit-curve-jobs/{job['job_id']}/download")
    assert dl.status_code == 200 and "monte_carlo_" in dl.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    assert {"mc_summary.csv", "mc_replicates.csv", "mc_summary.json"} <= set(zf.namelist())
    reps = list(csv.DictReader(io.StringIO(zf.read("mc_replicates.csv").decode())))
    assert len(reps) == 20 and "p1.area_pct" in reps[0]

    bad = client.post(f"/analysis/runs/{run_id}/monte-carlo-jobs", json={"fitting_step_index": 0, "n_replicates": 1})
    assert bad.status_code == 422
    sweep_like = client.get("/analysis/monte-carlo-jobs/fcjob_nope/summary")
    assert sweep_like.status_code == 404
