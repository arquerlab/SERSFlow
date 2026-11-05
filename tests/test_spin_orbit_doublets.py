"""F3: spin-orbit doublets — area_ratio for every line shape, recipe locks, partner helper, REST/MCP surfaces."""

from __future__ import annotations

import os

import numpy as np
import pytest

from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.fitting_specs import AREA_EXPORT_COMPONENT_TYPES, build_component_function, component_param_specs
from sersflow.core.preprocess.peak_area import area_per_height
from sersflow.core.spectrum import XY
from sersflow.core.xps.recipe_apply import apply_recipe_id
from sersflow.core.xps.spin_orbit import (
    SUBSHELL_AREA_RATIO,
    add_spin_orbit_partner,
    parse_nlj,
    partner_component_id,
    spin_orbit_pairs,
    subshell_from_text,
)

pytest.importorskip("lmfit")


def _areas(res, ctypes):
    out = []
    for m, ct in zip(res.mapping, ctypes):
        s, e = m["index_range"]
        pk = dict(zip(m["param_keys"], res.p_opt[s:e]))
        out.append(pk["amp"] * area_per_height(ct, pk) if "amp" in pk else None)
    return out


def test_theoretical_ratios_and_label_parsing() -> None:
    assert SUBSHELL_AREA_RATIO == {"p": 0.5, "d": pytest.approx(2 / 3), "f": 0.75}
    assert parse_nlj("IrCl_2p3/2").prefix == "ircl_" and parse_nlj("4f7_2_sat").suffix == "_sat"
    assert parse_nlj("peak_1") is None and parse_nlj("2p2/2") is None
    labels = ["4f7/2", "4f5/2", "4f7/2_sat", "4f5/2_sat", "5p3/2", "5p1/2", "IrCl_2p3/2", "HCl_2p1/2"]
    pairs = {(labels[p.main], labels[p.partner], p.area_ratio) for p in spin_orbit_pairs(labels)}
    assert pairs == {("4f7/2", "4f5/2", 0.75), ("4f7/2_sat", "4f5/2_sat", 0.75), ("5p3/2", "5p1/2", 0.5)}
    assert subshell_from_text("Co_2p3/2") == "p" and subshell_from_text("Ir_4f") == "f" and subshell_from_text("O_1s") is None
    assert partner_component_id("2p3_2", "p", set()) == "2p1_2"
    assert partner_component_id("peak_1", "p", set(), 2) == "peak_1_2p1_2"
    assert partner_component_id("Ag3d5_2", "d", {"Ag3d3_2"}) != "Ag3d3_2"


def _doublet_fit(ct: str, ratio: float):
    f, specs = build_component_function(ct)
    keys = [s.key for s in specs]

    def vec(pos: float, amp: float, fwhm: float) -> list[float]:
        v = []
        for s in specs:
            if s.key == "pos":
                v.append(pos)
            elif s.key == "amp":
                v.append(amp)
            elif s.key.startswith("fwhm") and s.key in ("fwhm", "fwhm_l"):
                v.append(fwhm)
            elif s.key == "fwhm_g":
                v.append(0.3)
            else:
                v.append(s.default if s.default is not None else 0.5)
        return v

    x = np.linspace(55.0, 72.0, 700)
    v1, v2 = vec(60.8, 1000.0, 0.9), vec(63.8, 1.0, 1.1)
    a1 = area_per_height(ct, dict(zip(keys, v1))) * 1000.0
    v2[keys.index("amp")] = ratio * a1 / area_per_height(ct, dict(zip(keys, v2)))
    y = f(x, *v1) + f(x, *v2) + np.random.default_rng(1).normal(0.0, 3.0, x.size)
    params = {
        "components": [{"component_id": "a", "component_type": ct}, {"component_id": "b", "component_type": ct}],
        "p0": vec(60.7, 800.0, 1.0) + vec(63.9, 300.0, 1.0),
        "bounds_lower": [s.lower_default for s in specs] * 2,
        "bounds_upper": [s.upper_default for s in specs] * 2,
        "vary": [k in ("pos", "amp", "fwhm") for k in keys] * 2,
        "technique_family": "xps",
        "param_links": [
            {"source_component_id": "b", "source_key": "amp", "target_component_id": "a", "target_key": "amp", "mode": "area_ratio", "ratio": ratio}
        ],
    }
    res = fit_curve(fit_problem_from_step_params(XY(x=x, y=y), params))
    a, b = _areas(res, [ct, ct])
    return a, b, res


@pytest.mark.parametrize("ct", sorted(AREA_EXPORT_COMPONENT_TYPES))
def test_area_ratio_link_holds_for_every_finite_area_line_shape(ct: str) -> None:
    a, b, _res = _doublet_fit(ct, 0.75)
    assert b / a == pytest.approx(0.75, rel=1e-9), ct


def test_area_ratio_link_for_la_recovers_truth() -> None:
    """Gap doc F3 'done when': area_ratio works for LA components."""
    a, b, res = _doublet_fit("la", 0.5)
    assert b / a == pytest.approx(0.5, rel=1e-12)
    assert res.p_opt[0] == pytest.approx(60.8, abs=0.01)


def test_ds_area_ratio_is_rejected() -> None:
    with pytest.raises(ValueError, match="no finite area"):
        from sersflow.core.preprocess.fitting_lmfit import _area_per_height_expr

        _area_per_height_expr("ds", "a", {("a", "fwhm"): "a_fwhm"})


def test_gl0_area_is_pure_gaussian_not_gl30() -> None:
    # 0 is a real value: area_per_height used to read GL(0) as GL(30) (``or`` default).
    assert area_per_height("gl", {"fwhm": 1.0, "m": 0.0}) == pytest.approx(area_per_height("gaussian", {"fwhm": 1.0}))


def test_ti_recipe_keeps_coster_kronig_fwhm_ratio_and_locks_area() -> None:
    out = apply_recipe_id("ti_2p_tio2_rutile", pass_energy=20)
    links = {(l["source_component_id"], l["source_key"]): l for l in out["param_links"]}
    fw = links[("2p1_2", "fwhm")]
    assert fw["mode"] == "scale" and fw["scale"] == pytest.approx(2.01 / 1.04)
    assert links[("2p1_2", "amp")]["mode"] == "area_ratio" and links[("2p1_2", "amp")]["ratio"] == 0.5
    assert ("2p1_2", "m") not in links  # GL(69) vs GL(67) in the table: shapes stay separate
    assert sum(1 for k in links if k[1] == "pos") == 1


@pytest.mark.parametrize(
    "rid,n_locks",
    [("sc_2p_sc0", 1), ("v_2p_v2o5", 1), ("cl_2p_ircl3_hydrated", 2), ("ir_4f_ir0", 2), ("ir_4f_iro2_anhydrous", 3)],
)
def test_doublet_recipes_lock_theoretical_area_ratios(rid: str, n_locks: int) -> None:
    out = apply_recipe_id(rid, pass_energy=20)
    so = [l for l in out["param_links"] if l["mode"] == "area_ratio" and l["ratio"] in (0.5, 0.75)]
    assert len(so) == n_locks
    free = apply_recipe_id(rid, pass_energy=20, lock_spin_orbit=False)
    assert not [l for l in free["param_links"] if l["mode"] == "area_ratio" and l["ratio"] in (0.5, 0.75)]


def test_one_member_recipe_stays_single_unless_partners_requested() -> None:
    single = apply_recipe_id("co_2p32_co3o4", pass_energy=20)
    assert not any(c["component_id"].endswith("2p1_2") for c in single["components"])
    both = apply_recipe_id("co_2p32_co3o4", pass_energy=20, spin_orbit_partner_splitting_eV=15.0)
    n = len(single["components"]) - 1  # minus Shirley
    assert len(both["components"]) == len(single["components"]) + n
    assert len(both["p0"]) == len(both["vary"]) == len(both["bounds_lower"]) == len(both["bounds_upper"])
    assert both["spin_orbit_partner"]["subshell"] == "p"
    with pytest.raises(ValueError, match="already has both"):
        apply_recipe_id("ti_2p_tio2_rutile", pass_energy=20, spin_orbit_partner_splitting_eV=5.7)


def test_co_2p_recipe_fit_holds_area_ratio_one_half() -> None:
    """Gap doc F3 'done when': a Co 2p recipe fit holds area(2p1/2)/area(2p3/2) = 0.5 exactly."""
    params = apply_recipe_id("co_2p32_coo", pass_energy=20, include_background=False, spin_orbit_partner_splitting_eV=15.6)
    ctypes = [c["component_type"] for c in params["components"]]
    # synthetic data: the seeded model itself (partners already at 0.5 through the seeds) plus noise
    x = np.linspace(805.0, 772.0, 660)
    y = np.full_like(x, 200.0)
    cursor = 0
    for c in params["components"]:
        f, specs = build_component_function(c["component_type"])
        n = len(specs)
        y = y + f(x, *params["p0"][cursor : cursor + n])
        cursor += n
    y = y * 1000.0 + np.random.default_rng(3).normal(0.0, 20.0, x.size)
    fit_params = dict(params)
    fit_params["components"] = [*params["components"], {"component_id": "off", "component_type": "polynomial_background", "degree": 0}]
    fit_params["p0"] = [*params["p0"], 150000.0]
    fit_params["bounds_lower"] = [*params["bounds_lower"], None]
    fit_params["bounds_upper"] = [*params["bounds_upper"], None]
    fit_params["vary"] = [*params["vary"], True]
    fit_params["technique_family"] = "xps"
    res = fit_curve(fit_problem_from_step_params(XY(x=x, y=y), fit_params))
    areas = _areas(res, [*ctypes, "polynomial_background"])
    ids = [m["component_id"] for m in res.mapping]
    for pid in params["spin_orbit_partner"]["component_ids"]:
        main = pid.removesuffix("_2p1_2")
        assert areas[ids.index(pid)] / areas[ids.index(main)] == pytest.approx(0.5, rel=1e-9), pid


def test_partner_helper_builds_links_and_validates() -> None:
    params = {
        "components": [{"component_id": "Ag3d5_2", "component_type": "la"}],
        "p0": [368.2, 1000.0, 0.6, 1.2, 2.0, 0.3],
        "bounds_lower": [367.0, 0.0, 0.1, 0.5, 0.5, 0.0],
        "bounds_upper": [369.0, None, 2.0, 5.0, 5.0, 1.0],
        "vary": [True, True, True, False, False, False],
    }
    out, pid = add_spin_orbit_partner(params, "Ag3d5_2", splitting_eV=6.0, subshell="d")
    assert pid == "Ag3d3_2" and len(out["p0"]) == 12
    assert out["p0"][6] == pytest.approx(374.2) and out["bounds_lower"][6] == pytest.approx(373.0)
    modes = {(l["source_key"], l["mode"]) for l in out["param_links"]}
    assert modes == {("pos", "offset"), ("fwhm", "equal"), ("alpha", "equal"), ("beta", "equal"), ("fwhm_g", "equal"), ("amp", "area_ratio")}
    assert params["p0"] == [368.2, 1000.0, 0.6, 1.2, 2.0, 0.3]  # input untouched
    with pytest.raises(ValueError, match="unknown component_id"):
        add_spin_orbit_partner(params, "nope", splitting_eV=6.0, subshell="d")
    with pytest.raises(ValueError, match="positive"):
        add_spin_orbit_partner(params, "Ag3d5_2", splitting_eV=-1.0, subshell="d")
    scaled, _ = add_spin_orbit_partner(params, "Ag3d5_2", splitting_eV=6.0, subshell="d", fwhm_ratio=2.0, lock_area=False)
    fw = next(l for l in scaled["param_links"] if l["source_key"] == "fwhm")
    assert fw["mode"] == "scale" and fw["scale"] == 2.0
    assert not any(l["source_key"] == "amp" for l in scaled["param_links"])


def test_rest_routes() -> None:
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    c = TestClient(app)
    r = c.get("/xps/fitting-recipes/co_2p32_coo/apply", params={"pass_energy": 20, "spin_orbit_partner_splitting_eV": 15.6})
    assert r.status_code == 200 and r.json()["spin_orbit_partner"]["subshell"] == "p"
    bad = c.get("/xps/fitting-recipes/ti_2p_tio2_rutile/apply", params={"spin_orbit_partner_splitting_eV": 5.7})
    assert bad.status_code == 400
    p = c.post(
        "/xps/spin-orbit-partner",
        json={
            "params": {"components": [{"component_id": "Si2p3_2", "component_type": "gl"}], "p0": [99.4, 100.0, 0.8, 30.0], "bounds_lower": [98.0, 0.0, 0.1, 0.0], "bounds_upper": [101.0, None, 3.0, 100.0], "vary": [True, True, True, False]},
            "component_id": "Si2p3_2",
            "splitting_eV": 0.61,
            "subshell": "p",
        },
    )
    assert p.status_code == 200 and p.json()["partner_id"] == "Si2p1_2"
    assert c.post("/xps/spin-orbit-partner", json={"params": {}, "component_id": "x", "splitting_eV": 1.0, "subshell": "s"}).status_code == 422
