"""K1: CasaXPS product GL(m) (true FWHM), SGL sum form, GL(m,n), and the gl -> sgl migration."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from sersflow.core.preprocess.fitting_models import (
    a_gl,
    a_sgl,
    gl,
    gl_gauss,
    gl_product_area_k,
    gl_product_fwhm_scale,
    pseudo_voigt,
    sgl,
)
from sersflow.core.preprocess.peak_area import area_per_height

LN2 = math.log(2.0)


def casaxps_gl(u: np.ndarray, m: float) -> np.ndarray:
    """CasaXPS Cookbook 2026 p.67, x in units of the width parameter F."""
    p = m / 100.0
    return np.exp(-(1.0 - p) * 4.0 * LN2 * u**2) / (1.0 + 4.0 * p * u**2)


@pytest.mark.parametrize("m", [0.0, 10.0, 30.0, 50.0, 70.0, 100.0])
def test_gl_is_the_casaxps_product_shape(m: float) -> None:
    # Same shape as the CasaXPS formula once F is mapped from the true FWHM.
    fwhm = 1.4
    f_param = fwhm / gl_product_fwhm_scale(m)
    x = np.linspace(-6.0, 6.0, 1201)
    np.testing.assert_allclose(gl(x, 0.0, 2.5, fwhm, m), 2.5 * casaxps_gl(x / f_param, m), rtol=1e-12, atol=1e-14)


@pytest.mark.parametrize("m", [0.0, 15.0, 30.0, 60.0, 95.0, 100.0])
def test_gl_fwhm_parameter_is_the_true_fwhm(m: float) -> None:
    fwhm = 1.7
    half = fwhm / 2.0
    assert gl(np.array([half]), 0.0, 1.0, fwhm, m)[0] == pytest.approx(0.5, abs=1e-9)
    assert gl(np.array([-half]), 0.0, 1.0, fwhm, m)[0] == pytest.approx(0.5, abs=1e-9)


def test_fwhm_scale_known_values() -> None:
    assert gl_product_fwhm_scale(0) == 1.0
    assert gl_product_fwhm_scale(100) == 1.0
    s30 = gl_product_fwhm_scale(30)
    # Direct check: at u = s/2 the CasaXPS shape is at half maximum.
    assert casaxps_gl(np.array([s30 / 2.0]), 30)[0] == pytest.approx(0.5, abs=1e-12)
    assert 0.95 < s30 < 0.97


@pytest.mark.parametrize("m", [5.0, 30.0, 50.0, 80.0])
def test_gl_area_matches_numeric_integral(m: float) -> None:
    fwhm = 1.3
    x = np.linspace(-4000.0, 4000.0, 4_000_001)
    y = gl(x, 0.0, 1.0, fwhm, m)
    numeric = float(np.trapezoid(y, x))
    # Tail beyond ±L: ∫ 1/(4p u²) over |u|>L/F, negligible for the Gaussian factor but bounded here.
    assert area_per_height("gl", {"fwhm": fwhm, "m": m}) == pytest.approx(numeric, rel=2e-4)
    assert gl_product_area_k(m) * fwhm == pytest.approx(area_per_height("gl", {"fwhm": fwhm, "m": m}))


def test_gl_limits_match_gaussian_and_lorentzian_areas() -> None:
    assert gl_product_area_k(0) == pytest.approx(math.sqrt(math.pi / (4 * LN2)))
    assert gl_product_area_k(100) == pytest.approx(math.pi / 2)


def test_sgl_is_the_old_sum_form() -> None:
    x = np.linspace(-5, 5, 301)
    np.testing.assert_allclose(sgl(x, 0.2, 3.0, 1.1, 30.0), pseudo_voigt(x, 0.2, 3.0, 1.1, 0.30))
    # product and sum differ for 0 < m < 100
    assert not np.allclose(gl(x, 0.2, 3.0, 1.1, 30.0), sgl(x, 0.2, 3.0, 1.1, 30.0))


def test_gl_gauss_reduces_to_gl_and_preserves_core_area() -> None:
    x = np.linspace(-30, 30, 30001)
    np.testing.assert_allclose(gl_gauss(x, 0.0, 1.0, 1.2, 30.0, 0.0), gl(x, 0.0, 1.0, 1.2, 30.0))
    y = gl_gauss(x, 0.0, 1.0, 1.2, 30.0, 0.8)
    assert float(y.max()) == pytest.approx(1.0, abs=1e-6)  # amp = height of the convolved profile
    # broader than the core, area per height from the numeric helper matches the curve
    half = x[y >= 0.5]
    assert (half.max() - half.min()) > 1.2
    # shape does not depend on the x range requested
    x2 = np.linspace(-3, 3, 601)
    np.testing.assert_allclose(gl_gauss(x2, 0.0, 1.0, 1.2, 30.0, 0.8), np.interp(x2, x, y), atol=2e-4)
    assert area_per_height("gl_gauss", {"fwhm": 1.2, "m": 30.0, "fwhm_g": 0.8}) == pytest.approx(
        float(np.trapezoid(y, x)), rel=5e-3
    )


def test_a_gl_uses_product_base_and_a_sgl_keeps_sum() -> None:
    x = np.linspace(-4, 4, 801)
    args = (0.0, 1.0, 1.0, 30.0, 0.0, 0.0, 0.0)  # no asymmetry, no convolution -> plain base
    np.testing.assert_allclose(a_gl(x, *args), gl(x, 0.0, 1.0, 1.0, 30.0), atol=1e-12)
    np.testing.assert_allclose(a_sgl(x, *args), sgl(x, 0.0, 1.0, 1.0, 30.0), atol=1e-12)


def test_area_ratio_link_works_for_product_gl() -> None:
    pytest.importorskip("lmfit")
    from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_curve

    x = np.linspace(770.0, 800.0, 600)
    true = gl(x, 780.0, 100.0, 1.5, 30.0) + gl(x, 795.0, 50.0 * 1.5 / 2.0, 2.0, 30.0)
    rng = np.random.default_rng(1)
    y = true + rng.normal(0, 0.5, x.size)
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[
                FitComponent(component_type="gl", component_id="a"),
                FitComponent(component_type="gl", component_id="b"),
            ],
            p0=[780.2, 90.0, 1.4, 30.0, 795.1, 30.0, 2.1, 30.0],
            bounds_lower=[775.0, 0.0, 0.5, 0.0, 790.0, 0.0, 0.5, 0.0],
            bounds_upper=[785.0, None, 4.0, 100.0, 800.0, None, 4.0, 100.0],
            vary=[True, True, True, False, True, True, True, False],
            technique_family="xps",
            param_links=[
                {
                    "source_component_id": "b",
                    "source_key": "amp",
                    "target_component_id": "a",
                    "target_key": "amp",
                    "mode": "area_ratio",
                    "ratio": 0.5,
                }
            ],
        )
    )
    p = res.p_opt
    area_a = p[1] * area_per_height("gl", {"fwhm": p[2], "m": p[3]})
    area_b = p[5] * area_per_height("gl", {"fwhm": p[6], "m": p[7]})
    assert area_b / area_a == pytest.approx(0.5, rel=1e-9)


# --- migration ---------------------------------------------------------------------------------


def _fitting_pipeline(ctypes: list[str]) -> dict:
    return {
        "steps": [
            {"name": "crop", "params": {"min_x": 1, "max_x": 2}},
            {
                "name": "fitting",
                "params": {"components": [{"component_id": f"p{i}", "component_type": c} for i, c in enumerate(ctypes)]},
            },
        ]
    }


def test_migrate_legacy_gl_rewrites_only_fitting_components() -> None:
    from sersflow.core.pipeline.lineshape_migration import migrate_legacy_gl

    wrapper = {"pipeline": _fitting_pipeline(["gl", "a_gl", "la", "sgl"]), "note": {"component_type": "gl"}}
    assert migrate_legacy_gl(wrapper) == 2
    types = [c["component_type"] for c in wrapper["pipeline"]["steps"][1]["params"]["components"]]
    assert types == ["sgl", "a_sgl", "la", "sgl"]
    assert wrapper["note"] == {"component_type": "gl"}  # not a fitting step
    assert migrate_legacy_gl(wrapper) == 0  # idempotent


def test_db_migration_rewrites_stored_pipelines_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    from sersflow.infra.lineshape_db_migration import migrate_gl_to_sgl
    from sersflow.infra.sqlite_db import connect

    with connect() as con:
        con.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, pipeline_json TEXT)")
        con.execute("CREATE TABLE analysis_runs (run_id TEXT PRIMARY KEY, pipeline_json TEXT)")
        con.execute("INSERT INTO sessions VALUES ('s1', ?)", (json.dumps(_fitting_pipeline(["gl"])),))
        con.execute(
            "INSERT INTO analysis_runs VALUES ('r1', ?)",
            (json.dumps({"pipeline": _fitting_pipeline(["a_gl", "gaussian"])}),),
        )
        con.execute("INSERT INTO analysis_runs VALUES ('r2', NULL)")

    out = migrate_gl_to_sgl()
    assert out["applied"] and out["components_renamed"] == 2
    assert out["rows_changed"] == {"sessions": 1, "analysis_runs": 1}
    with connect() as con:
        s = json.loads(con.execute("SELECT pipeline_json FROM sessions").fetchone()[0])
        r = json.loads(con.execute("SELECT pipeline_json FROM analysis_runs WHERE run_id='r1'").fetchone()[0])
    assert s["steps"][1]["params"]["components"][0]["component_type"] == "sgl"
    assert [c["component_type"] for c in r["pipeline"]["steps"][1]["params"]["components"]] == ["a_sgl", "gaussian"]

    # Marker: a later 'gl' (new product semantics) is never touched again.
    with connect() as con:
        con.execute("UPDATE sessions SET pipeline_json = ?", (json.dumps(_fitting_pipeline(["gl"])),))
    assert migrate_gl_to_sgl()["applied"] is False
    with connect() as con:
        s = json.loads(con.execute("SELECT pipeline_json FROM sessions").fetchone()[0])
    assert s["steps"][1]["params"]["components"][0]["component_type"] == "gl"


def test_migrated_pipeline_reproduces_old_numbers() -> None:
    """A legacy gl (sum) pipeline migrated to sgl gives the same fit curve as before K1."""
    from sersflow.core.pipeline.lineshape_migration import migrate_legacy_gl
    from sersflow.core.preprocess.fitting import evaluate_fit_curves, fit_problem_from_step_params
    from sersflow.core.spectrum import XY

    params = {
        "components": [{"component_id": "p", "component_type": "gl"}],
        "p0": [780.0, 10.0, 1.5, 30.0],
        "bounds_lower": [770.0, 0.0, 0.1, 0.0],
        "bounds_upper": [790.0, None, 5.0, 100.0],
        "technique_family": "xps",
    }
    step = {"name": "fitting", "params": params}
    migrate_legacy_gl(step)
    x = np.linspace(770, 790, 201)
    prob = fit_problem_from_step_params(XY(x=x, y=np.zeros_like(x)), step["params"])
    res = evaluate_fit_curves(prob, [780.0, 10.0, 1.5, 30.0])
    np.testing.assert_allclose(res.y_hat, pseudo_voigt(x, 780.0, 10.0, 1.5, 0.30), atol=1e-9)


def test_pipeline_package_v1_import_is_migrated_and_export_is_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    client = TestClient(app)
    pipe = _fitting_pipeline(["gl"])
    pipe["technique_family"] = "xps"
    r1 = client.post(
        "/pipelines/import",
        json={"schema_version": "sersflow.pipeline.v1", "name": "old", "pipeline": pipe, "technique_family": "xps"},
    )
    assert r1.status_code == 200, r1.text
    comps = r1.json()["item"]["pipeline"]["steps"][1]["params"]["components"]
    assert comps[0]["component_type"] == "sgl"

    r2 = client.post(
        "/pipelines/import",
        json={"schema_version": "sersflow.pipeline.v2", "name": "new", "pipeline": pipe, "technique_family": "xps"},
    )
    assert r2.json()["item"]["pipeline"]["steps"][1]["params"]["components"][0]["component_type"] == "gl"

    pid = r2.json()["item"]["pipeline_id"]
    exp = client.get(f"/pipelines/{pid}/export")
    assert exp.status_code == 200
    assert json.loads(exp.content)["schema_version"] == "sersflow.pipeline.v2"

    bad = client.post("/pipelines/import", json={"schema_version": "x", "pipeline": pipe})
    assert bad.status_code == 400


def test_fitting_models_catalog_lists_both_forms() -> None:
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    body = TestClient(app).get("/fitting/models").json()
    items = body if isinstance(body, list) else body.get("components") or body.get("items") or []
    types = {c["component_type"] for c in items}
    assert {"gl", "sgl", "gl_gauss", "a_gl", "a_sgl"} <= types
