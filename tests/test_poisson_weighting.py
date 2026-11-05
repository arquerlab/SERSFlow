"""F1: Poisson-weighted fitting, normalised residual STD, weighted reduced chi2, variance propagation."""

from __future__ import annotations

import os

import numpy as np
import pytest

from sersflow.core.pipeline.steps import DEFAULT_STEPS
from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.fitting_models import gl
from sersflow.core.spectrum import XY, poisson_variance_from_meta

pytest.importorskip("lmfit")

X = np.linspace(775.0, 790.0, 601)


def _true_counts() -> np.ndarray:
    return gl(X, 780.0, 4000.0, 1.6, 30.0) + gl(X, 783.0, 900.0, 2.2, 30.0) + 400.0


def _params(weighting: str | None = None) -> dict:
    p = {
        "components": [
            {"component_id": "a", "component_type": "gl"},
            {"component_id": "b", "component_type": "gl"},
            {"component_id": "bg", "component_type": "polynomial_background", "degree": 0},
        ],
        "p0": [780.2, 3500.0, 1.5, 30.0, 783.2, 800.0, 2.0, 30.0, 350.0],
        "bounds_lower": [778.0, 0.0, 0.5, 0.0, 781.0, 0.0, 0.5, 0.0, 0.0],
        "bounds_upper": [782.0, None, 4.0, 100.0, 785.0, None, 4.0, 100.0, None],
        "vary": [True, True, True, False, True, True, True, False, True],
        "technique_family": "xps",
    }
    if weighting is not None:
        p["weighting"] = weighting
    return p


def _poisson_xy(seed: int = 0, scale: float = 1.0) -> XY:
    counts = np.random.default_rng(seed).poisson(_true_counts()).astype(float)
    y = counts * scale
    meta = {"y_unit": "counts"}
    var, kind = poisson_variance_from_meta(y, meta)
    return XY(x=X, y=y, var=var, var_kind=kind)


def test_poisson_fit_on_simulated_counts_gives_chi2_and_resid_std_near_one() -> None:
    chis, stds = [], []
    for seed in range(8):
        prob = fit_problem_from_step_params(_poisson_xy(seed), _params())
        assert prob.weighting == "poisson" and prob.sigma is not None
        d = fit_curve(prob).diagnostics
        assert d.weighting == "poisson"
        chis.append(d.chi2_reduced_weighted)
        stds.append(d.residual_std_normalised)
    assert np.mean(chis) == pytest.approx(1.0, abs=0.08)
    assert np.mean(stds) == pytest.approx(1.0, abs=0.05)


def test_scaled_counts_use_relative_poisson_and_recover_the_gain() -> None:
    xy = _poisson_xy(1, scale=0.37)  # e.g. normalised synchrotron data: non-integer "counts"
    assert xy.var_kind == "relative"
    prob = fit_problem_from_step_params(xy, _params())
    assert prob.weighting == "poisson_relative"
    d = fit_curve(prob).diagnostics
    assert d.weighting == "poisson_relative"
    # var = g*y with g = scale; one spectrum scatters by ~sqrt(2/N), so average a few replicates
    gains = [
        fit_curve(fit_problem_from_step_params(_poisson_xy(s, scale=0.37), _params())).diagnostics.poisson_gain
        for s in range(6)
    ]
    assert np.mean(gains) == pytest.approx(0.37, rel=0.06)
    assert d.chi2_reduced_weighted is None  # no absolute meaning
    assert d.residual_std_normalised == pytest.approx(1.0, abs=0.05)


def test_weighted_and_unweighted_parameters_agree_within_noise_but_differ() -> None:
    xy = _poisson_xy(2)
    pw = fit_curve(fit_problem_from_step_params(xy, _params())).p_opt
    pn = fit_curve(fit_problem_from_step_params(xy, _params("none"))).p_opt
    assert not np.allclose(pw, pn)
    assert pw[0] == pytest.approx(780.0, abs=0.02) and pn[0] == pytest.approx(780.0, abs=0.02)


def test_modes_and_fallbacks() -> None:
    xy = _poisson_xy(3)
    assert fit_problem_from_step_params(xy, _params("none")).weighting == "none"
    assert fit_problem_from_step_params(xy, _params("poisson_relative")).weighting == "poisson_relative"
    no_var = XY(x=xy.x, y=xy.y)
    p = fit_problem_from_step_params(no_var, _params())
    assert p.weighting == "none" and "no counting statistics" in p.weighting_note
    vib = dict(_params(), technique_family="vibrational")
    vib["components"] = [{"component_id": "a", "component_type": "gaussian"}]
    vib.update(p0=[780.0, 4000.0, 1.6], bounds_lower=[778.0, 0.0, 0.5], bounds_upper=[782.0, None, 4.0])
    vib.pop("vary")
    p = fit_problem_from_step_params(xy, vib)
    assert p.weighting == "none" and "XPS only" in p.weighting_note


def test_integer_cps_with_dwell_and_scans_is_absolute() -> None:
    counts = np.array([10.0, 25.0, 400.0])
    meta = {"y_unit": "cps", "dwell_time_s": 0.1, "n_scans": 5}
    var, kind = poisson_variance_from_meta(counts / 0.5, meta)
    assert kind == "absolute"
    np.testing.assert_allclose(var, counts / 0.5**2)


def test_variance_survives_safe_steps_and_is_dropped_by_smoothing() -> None:
    xy = _poisson_xy(4)
    out = DEFAULT_STEPS["crop"].transform(xy, {"min_x": 777.0, "max_x": 788.0})
    assert out.var is not None and out.var.shape == out.y.shape and out.var_kind == "absolute"
    norm = DEFAULT_STEPS["normalize"].transform(out, {"method": "max"})
    k = float(np.max(out.y))
    np.testing.assert_allclose(norm.var, out.var / k**2)
    cal = DEFAULT_STEPS["x_axis_calibration"].transform(norm, {"method": "fixed_offset", "offset": 0.5})
    assert cal.var is not None
    base = DEFAULT_STEPS["baseline"].transform(cal, {"method": "shirley"})
    np.testing.assert_allclose(base.var, cal.var)  # weights stay on the raw counts
    smooth = DEFAULT_STEPS["noise_savgol"].transform(base, {"window_length": 11, "polyorder": 3})
    assert smooth.var is None


def test_normalised_and_shirley_flip_path() -> None:
    xy = _poisson_xy(5)
    params = _params()
    params["components"] = [
        {"component_id": "bg", "component_type": "shirley_bg"},
        {"component_id": "a", "component_type": "gl"},
    ]
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    bg_n = len(component_param_specs("shirley_bg"))
    bg_specs = component_param_specs("shirley_bg")
    params["p0"] = [s.default if s.default is not None else 0.0 for s in bg_specs] + [780.0, 3500.0, 1.6, 30.0]
    params["bounds_lower"] = [s.lower_default for s in bg_specs] + [778.0, 0.0, 0.5, 0.0]
    params["bounds_upper"] = [s.upper_default for s in bg_specs] + [782.0, None, 4.0, 100.0]
    params["vary"] = [True] * bg_n + [True, True, True, False]
    res = fit_curve(fit_problem_from_step_params(xy, params))  # ascending x -> flipped for lmfitxps
    assert res.diagnostics.weighting == "poisson"
    assert np.isfinite(res.diagnostics.residual_std_normalised)


def test_feature_columns_carry_weighting() -> None:
    from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
    from sersflow.core.metrics.fitting_features import collect_fitting_features_for_pipeline

    pipe = Pipeline(steps=[PipelineStep(name="fitting", params=_params())], technique_family="xps")
    keys, vals = collect_fitting_features_for_pipeline(_poisson_xy(6), pipe)
    assert vals["fit_gof_weighting"] == 1.0
    assert vals["fit_gof_chi2_reduced_weighted"] == pytest.approx(1.0, abs=0.25)
    assert "fit_gof_residual_std_normalised" in keys and "fit_gof_poisson_gain" in keys


def test_rest_fit_with_inline_variance_returns_normalised_residual() -> None:
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    xy = _poisson_xy(7)
    p = _params()
    body = {
        "target": {"kind": "inline", "x": xy.x.tolist(), "y": xy.y.tolist(), "y_variance": xy.var.tolist(), "variance_kind": "absolute"},
        "components": p["components"],
        "p0": p["p0"],
        "bounds": {"lower": p["bounds_lower"], "upper": p["bounds_upper"]},
        "vary": p["vary"],
        "technique_family": "xps",
        "return_curve": True,
    }
    r = TestClient(app).post("/fitting/fit", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["diagnostics"]["weighting"] == "poisson"
    assert out["diagnostics"]["chi2_reduced_weighted"] == pytest.approx(1.0, abs=0.25)
    rn = np.array([v for v in out["residual_normalised"] if v is not None])
    assert rn.size == xy.x.size and np.std(rn) == pytest.approx(1.0, abs=0.15)

    body["weighting"] = "none"
    out2 = TestClient(app).post("/fitting/fit", json=body).json()
    assert out2["diagnostics"]["weighting"] == "none" and out2["residual_normalised"] is None
