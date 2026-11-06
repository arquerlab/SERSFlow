"""B1 backgrounds, L1 line shapes, M1 reference spectra, S1 test peak model."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.fitting_models import ds, gl
from sersflow.core.preprocess.xps_extra_components import (
    endpoint_levels,
    erfc_edge_position,
    erfc_step_bg,
    shirley_profile,
    tougaard_u4_bg,
)
from sersflow.core.spectrum import XY

pytest.importorskip("lmfit")


def _p(comps, p0, lo, hi, vary=None, **kw):
    return {"components": comps, "p0": p0, "bounds_lower": lo, "bounds_upper": hi, "vary": vary or [True] * len(p0), "technique_family": "xps", **kw}


# ------------------------------------------------------------------------------------------------ B1


def test_endpoint_levels_av_width_and_offsets() -> None:
    x = np.arange(10.0)
    y = np.array([1.0, 3.0, 5.0, 0, 0, 0, 0, 10.0, 20.0, 30.0])
    assert endpoint_levels(x, y, avg_width=1) == (2.0, 25.0)  # +-1 channel at an edge: end channel + 1 inner
    assert endpoint_levels(x, y, avg_width=0) == (1.0, 30.0)
    lo, hi = endpoint_levels(x, y, avg_width=0, offset_low_pct=50, offset_high_pct=10)
    assert (lo, hi) == (0.5, 27.0)
    assert endpoint_levels(x, y, avg_width=100) == (1.0, 30.0)  # window too large: no averaging (CasaXPS)


def test_static_shirley_and_linear_with_averaging_and_offsets() -> None:
    from sersflow.core.preprocess.baseline import correct_baseline

    x = np.linspace(770, 790, 400)
    rng = np.random.default_rng(0)
    y = gl(x, 780, 1000, 2, 30) + 100 + np.where(x > 780, 50, 0) + rng.normal(0, 5, x.size)
    _c, info = correct_baseline(y, x=x, method="shirley", avg_width=10, offset_high_pct=10)
    b = info["baseline"]
    assert b[0] == pytest.approx(np.mean(y[:11]), abs=1e-6)
    assert b[-1] == pytest.approx(0.9 * np.mean(y[-11:]), abs=1e-6)
    clean = gl(x, 780, 1000, 2, 30) + 100 + np.where(x > 780, 50, 0)
    _c, info0 = correct_baseline(clean, x=x, method="shirley", avg_width=10)
    assert np.all(np.diff(info0["baseline"]) >= -1e-9)  # monotonic Shirley step on noise-free data
    _c, info = correct_baseline(y, x=x, method="linear", avg_width=3)
    assert info["baseline"][0] == pytest.approx(np.mean(y[:4])) and info["baseline"][-1] == pytest.approx(np.mean(y[-4:]))
    # defaults keep the lmfitxps Shirley (results unchanged for existing pipelines)
    _c, legacy = correct_baseline(y, x=x, method="shirley")
    assert legacy["baseline"].shape == y.shape


def test_active_shirley_options_move_the_endpoint_level() -> None:
    x = np.linspace(790, 770, 400)
    y = gl(x, 780, 1000, 2, 30) + 100 + np.where(x > 780, 50, 0)
    base = [{"component_id": "bg", "component_type": "shirley_bg"}, {"component_id": "p", "component_type": "gl"}]
    p0 = [0.0, 0.0, 780.2, 900, 1.8, 30]
    lo = [0.0, None, 778, 0, 0.5, 0]
    hi = [None, None, 782, None, 5, 100]
    vary = [True, True, True, True, True, False]
    r0 = fit_curve(fit_problem_from_step_params(XY(x=x, y=y), _p(base, p0, lo, hi, vary)))
    off = [dict(base[0], offset_low_pct=20.0), base[1]]
    r1 = fit_curve(fit_problem_from_step_params(XY(x=x, y=y), _p(off, p0, lo, hi, vary)))
    assert r0.p_opt[1] == pytest.approx(100.0, abs=1.0)
    assert r1.p_opt[1] == pytest.approx(80.0, abs=1.0)  # const lowered by 20 %


def test_erfc_step_recovers_a_fermi_edge_and_its_edge_position() -> None:
    x = np.linspace(-2, 2, 400)
    y = erfc_step_bg(x, 0.05, 1000.0, 0.3, 50.0) + np.random.default_rng(1).normal(0, 5, x.size)
    r = fit_curve(
        fit_problem_from_step_params(
            XY(x=x, y=y),
            _p([{"component_id": "ef", "component_type": "erfc_step_bg"}], [0.0, 0.0, 0.5, 0.0], [-1, None, 0.01, None], [1, None, 3, None]),
        )
    )
    pos, height, fwhm, const = r.p_opt
    assert pos == pytest.approx(0.05, abs=0.01) and height == pytest.approx(1000, rel=0.02)
    assert fwhm == pytest.approx(0.3, rel=0.05) and const == pytest.approx(50, abs=3)
    a = 0.3 / (2 * np.sqrt(np.log(2)))
    assert erfc_edge_position(0.05, 0.3) == pytest.approx(0.05 - a * np.sqrt(np.pi) / 2)
    # the step position is a calibration key (x-axis calibration offers *_pos)
    from sersflow.core.preprocess.x_axis_calibration import calibration_pos_keys_for_step

    assert "fit_ef_pos" in calibration_pos_keys_for_step({"components": [{"component_id": "ef", "component_type": "erfc_step_bg"}]})


def test_tougaard_t0_onset_and_u2_form() -> None:
    x = np.linspace(270, 300, 301)
    y = gl(x, 285, 1000, 1.5, 30) + 50
    full = tougaard_u4_bg(x, y, 2866, 1643, 1, 0, 0)
    gap = tougaard_u4_bg(x, y, 2866, 1643, 1, 0, 5.0)
    assert np.all(gap <= full + 1e-9)
    i = np.searchsorted(x, 288.0)  # 3 eV above the peak: inside the 5 eV gap -> no background from it
    assert (gap[i] - gap[0]) < 0.05 * (full[i] - full[0])  # only the far peak tail lies more than T0 below


def test_shirley_of_peak_component_recovers_k() -> None:
    x = np.linspace(770, 790, 600)
    y = gl(x, 780, 1000, 2, 30) + shirley_profile(x, gl(x, 780, 1000, 2, 30), 0.05) + 100
    y = y + np.random.default_rng(2).normal(0, 3, x.size)
    comps = [
        {"component_id": "off", "component_type": "polynomial_background", "degree": 0},
        {"component_id": "p", "component_type": "gl"},
        {"component_id": "sb", "component_type": "shirley_of_bg", "of": "p"},
    ]
    r = fit_curve(
        fit_problem_from_step_params(
            XY(x=x, y=y),
            _p(comps, [90, 779.5, 800, 1.8, 30, 0.01, 0], [None, 775, 0, 0.5, 0, 0, -5], [None, 785, None, 5, 100, None, 5], [True, True, True, True, False, True, False]),
        )
    )
    assert r.p_opt[5] == pytest.approx(0.05, rel=0.05)
    assert r.p_opt[0] == pytest.approx(100, abs=3)


# ------------------------------------------------------------------------------------------------ L1


def test_ds_area_is_integrated_over_the_fit_window() -> None:
    from sersflow.core.metrics.fit_uncertainty import component_uncertainty_rows

    x = np.linspace(60, 70, 500)
    y = ds(x, 63, 1000, 0.4, 0.15) + np.random.default_rng(3).normal(0, 3, x.size)
    r = fit_curve(
        fit_problem_from_step_params(
            XY(x=x, y=y), _p([{"component_id": "d", "component_type": "ds"}], [63.1, 900, 0.5, 0.1], [62, 0, 0.05, 0], [64, None, 2, 0.5])
        )
    )
    row = component_uncertainty_rows(r)[0]
    trap = getattr(np, "trapezoid", None) or np.trapz
    truth = trap(ds(x, *r.p_opt), x)
    assert row["area"] == pytest.approx(truth, rel=2e-3) and row["area_stderr"] > 0
    # a narrower window gives a smaller area (window-dependent by construction)
    narrow = fit_curve(
        fit_problem_from_step_params(
            XY(x=x, y=y),
            _p([{"component_id": "d", "component_type": "ds"}], [63.1, 900, 0.5, 0.1], [62, 0, 0.05, 0], [64, None, 2, 0.5], fit_min_x=61.0, fit_max_x=65.0),
        )
    )
    assert component_uncertainty_rows(narrow)[0]["area"] < row["area"]


def test_casaxps_lineshape_parser_round_trips_every_recipe_string() -> None:
    from sersflow.core.xps.casaxps_lineshape import LineshapeParseError, format_casaxps_lineshape, parse_casaxps_lineshape

    d = json.loads(Path("src/sersflow/core/xps/data/fitting_recipes.json").read_text(encoding="utf-8"))
    seen = 0
    for fit in d["compound_fits"]:
        for peak in fit["peaks"]:
            ls = peak["lineshape"]
            s = ls.get("casaxps")
            if not s:
                continue
            seen += 1
            r = parse_casaxps_lineshape(s)
            assert r["kind"] == ls["kind"], s
            assert format_casaxps_lineshape(r["kind"], r["params"], spaced=", " in s) == s
            for k, v in r["params"].items():
                assert float(ls["params"][k]) == float(v), (s, k)
    assert seen > 400
    sb = parse_casaxps_lineshape("SB(0)LA(1,43)")
    assert sb["kind"] == "la" and sb["shirley_profile"] is True
    assert parse_casaxps_lineshape("GL(30,0.4)")["kind"] == "gl_gauss"
    assert parse_casaxps_lineshape("DS(0.3,600)")["params"] == {"alpha": 0.3, "n": 600}
    for bad in ("T(2)GL(30)", "TP(1,1,0)", "XYZ(1)", "GL(a)"):
        with pytest.raises(LineshapeParseError):
            parse_casaxps_lineshape(bad)


# ------------------------------------------------------------------------------------------------ M1


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app
    from sersflow.core.preprocess.reference_component import clear_cache

    clear_cache()
    return TestClient(app)


X = np.linspace(770, 800, 601)
CO2 = gl(X, 780.5, 1, 2.6, 30) + 0.5 * gl(X, 786.5, 1, 5, 30)
CO3 = gl(X, 779.6, 1, 2.0, 30) + 0.15 * gl(X, 789.8, 1, 4, 30)


def _two_refs(api):
    r1 = api.post("/references", json={"name": "CoO std", "x": X.tolist(), "y": CO2.tolist(), "source": {"session_id": "s1"}}).json()
    r2 = api.post("/references", json={"name": "Co3O4 std", "x": X.tolist(), "y": CO3.tolist()}).json()
    return r1, r2


def test_reference_library_crud_and_imports(api, tmp_path: Path) -> None:
    r1, _r2 = _two_refs(api)
    assert r1["source"]["kind"] == "processed" and len(r1["sha256"]) == 64
    assert api.get("/references").json()["count"] == 2
    txt = "# energy, counts\nBE,I\n" + "\n".join(f"{a}\t{b}" for a, b in zip(X[::10], CO2[::10]))
    imp = api.post("/references/import", json={"name": "lit", "content": txt, "filename": "lit.txt"}).json()
    assert imp["n_points"] == len(X[::10]) and imp["source"]["kind"] == "text_import"
    assert api.post("/references/import", json={"name": "bad", "content": "a b\n"}).status_code == 400
    assert api.post("/references", json={"name": "neg", "x": [1, 2, 3], "y": [-1, -2, -3]}).status_code == 400
    win = api.post("/references", json={"name": "win", "x": X.tolist(), "y": CO2.tolist(), "x_min": 775, "x_max": 790}).json()
    assert win["x_min"] >= 775 and win["x_max"] <= 790
    assert api.patch(f"/references/{imp['reference_id']}", json={"name": "lit2"}).json()["name"] == "lit2"
    assert api.delete(f"/references/{imp['reference_id']}").json() == {"deleted": True}
    assert api.get(f"/references/{imp['reference_id']}").status_code == 404

    # from a raw dataset spectrum
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.datasets_store import create_dataset
    from tests.test_vamas_iso import _block, _header, _write

    (tmp_path / "b1").mkdir()
    _write(tmp_path / "b1", _header(n_blocks=1) + _block(x_start=800.0, x_step=-0.05, columns=[list(100 * CO2[::-1] + 5)]), name="r.vms")
    ds_ = create_dataset(
        owner_user_id="dev",
        metadata=DatasetMetadata(name="refs", technique_family="xps"),
        spectra=[SpectrumRef(spectrum_id="sp_r", relative_path="b1/r.vms", record_index=0)],
    )
    raw = api.post("/references/from-dataset", json={"name": "raw CoO", "dataset_id": ds_.dataset_id, "spectrum_id": "sp_r"})
    assert raw.status_code == 200, raw.text
    assert raw.json()["source"]["kind"] == "dataset_raw" and raw.json()["n_points"] == 601


def test_two_reference_mixture_is_recovered_by_nnls_and_mixes_with_gl(api) -> None:
    """Gap doc M1 'done when': correct fractions of two measured references, and a mixed fit with a GL peak."""
    from sersflow.core.metrics.fit_uncertainty import component_uncertainty_rows

    r1, r2 = _two_refs(api)
    trap = getattr(np, "trapezoid", None) or np.trapz
    y = 1500 * CO2 / trap(CO2, X) + 3500 * CO3 / trap(CO3, X)
    y = np.random.default_rng(4).poisson(y + 20).astype(float) - 20
    comps = [
        {"component_id": "CoO", "component_type": "reference_spectrum", "reference_id": r1["reference_id"], "reference_sha256": r1["sha256"]},
        {"component_id": "Co3O4", "component_type": "reference_spectrum", "reference_id": r2["reference_id"]},
    ]
    p = _p(comps, [1000, 0, 1000, 0], [0, -1, 0, -1], [None, 1, None, 1], [True, False, True, False])
    res = fit_curve(fit_problem_from_step_params(XY(x=X, y=y), p))
    assert "NNLS" in (res.diagnostics.weighting_note or "")
    rows = component_uncertainty_rows(res)
    assert rows[0]["area_pct"] == pytest.approx(30.0, abs=1.0) and rows[1]["area_pct"] == pytest.approx(70.0, abs=1.0)
    assert rows[0]["area_pct_stderr"] > 0

    y2 = y + gl(X, 775, 400, 1.5, 30)
    comps2 = [*comps, {"component_id": "extra", "component_type": "gl"}]
    p2 = _p(comps2, [1000, 0, 1000, 0, 775.3, 300, 1.4, 30], [0, -1, 0, -1, 773, 0, 0.5, 0], [None, 1, None, 1, 777, None, 4, 100], [True, False, True, False, True, True, True, False])
    res2 = fit_curve(fit_problem_from_step_params(XY(x=X, y=y2), p2))
    a = [r["area"] for r in component_uncertainty_rows(res2)]
    assert a[0] / (a[0] + a[1]) == pytest.approx(0.30, abs=0.01)
    assert res2.p_opt[4] == pytest.approx(775.0, abs=0.05)
    # a changed reference is refused (reproducibility)
    bad = [dict(comps[0], reference_sha256="0" * 64), comps[1]]
    with pytest.raises(ValueError, match="sha256 mismatch"):
        fit_curve(fit_problem_from_step_params(XY(x=X, y=y), _p(bad, p["p0"], p["bounds_lower"], p["bounds_upper"], p["vary"])))


# ------------------------------------------------------------------------------------------------ S1


def _two_peak_fit_request(x, y):
    return {
        "target": {"kind": "inline", "x": x.tolist(), "y": y.tolist()},
        "components": [
            {"component_id": "a", "component_type": "gl"},
            {"component_id": "b", "component_type": "gl"},
            {"component_id": "bg", "component_type": "polynomial_background", "degree": 0},
        ],
        "p0": [780, 900, 2, 30, 782, 300, 2.5, 30, 40],
        "bounds": {"lower": [778, 0, 0.5, 0, 780, 0, 0.5, 0, None], "upper": [782, None, 5, 100, 784, None, 5, 100, None]},
        "vary": [True, True, True, False, True, True, True, False, True],
        "technique_family": "xps",
    }


def test_test_peak_model_scan_and_noise(api) -> None:
    """Gap doc S1 'done when': scan the position of one component and get chi2 and %area profiles."""
    x = np.linspace(770, 795, 500)
    y = gl(x, 780, 1000, 2.2, 30) + gl(x, 781.8, 400, 2.6, 30) + 50 + np.random.default_rng(0).normal(0, 8, x.size)
    fit = _two_peak_fit_request(x, y)
    r = api.post("/fitting/test-peak-model", json={"fit": fit, "mode": "scan", "key": "pos", "component_id": "b", "values": list(np.linspace(781, 783, 9))})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["scanned"] == ["b.pos"] and len(out["points"]) == 9
    assert out["best_value"] == pytest.approx(781.8, abs=0.26)
    pct_b = [p["area_pct"]["b"] for p in out["points"]]
    assert pct_b[0] > pct_b[-1] + 30  # %area of b changes strongly along the scan
    chi = [p["chi2"] for p in out["points"]]
    assert min(chi) == chi[[p["value"] for p in out["points"]].index(out["best_value"])]

    allm = api.post("/fitting/test-peak-model", json={"fit": fit, "mode": "scan", "key": "m", "component_type": "gl", "values": [10, 30, 50]}).json()
    assert allm["scanned"] == ["a.m", "b.m"] and allm["points"][1]["params"]["a.m"] == 30.0

    noise = api.post("/fitting/test-peak-model", json={"fit": fit, "mode": "noise", "n_replicates": 15, "seed": 2}).json()
    assert noise["n_ok"] == 15 and len(noise["overlay"]) == 15
    comp_b = next(c for c in noise["components"] if c["component_id"] == "b")
    assert len(comp_b["area_pct"]) == 15 and comp_b["area_pct_spread"]["sd"] > 0
    bad = api.post("/fitting/test-peak-model", json={"fit": fit, "mode": "scan", "key": "zz", "values": [1]})
    assert bad.status_code == 400 and "no parameter" in bad.json()["detail"]


def test_run_sweep_summary_has_pct_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_run_provenance_api import _wait_job, _xps_fit_run

    client, run_id = _xps_fit_run(tmp_path, monkeypatch)
    r = client.post(f"/analysis/runs/{run_id}/sweep-jobs", json={"fitting_step_index": 0, "grid": [{"component_id": "p1", "key": "fwhm", "values": [2.5, 3.5]}]})
    job = _wait_job(client, r.json()["job_id"])
    s = client.get(f"/analysis/sweep-jobs/{job['job_id']}/summary").json()
    assert s["axes"] == ["p1.fwhm"] and s["pct_columns"] == ["pct:p1"]
    assert all(row["pct:p1_mean"] == pytest.approx(100.0) for row in s["summary"])
    assert client.get("/analysis/sweep-jobs/fcjob_nope/summary").status_code == 404
