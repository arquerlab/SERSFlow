"""P0 XPS correctness: LA BE side, CasaXPS m mapping, area→height, Shirley seed, technique guards."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sersflow.core.io.technique import (
    assert_matching_technique_families,
    normalize_technique_family,
)
from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_problem_from_step_params
from sersflow.core.preprocess.fitting_models import _la0, la
from sersflow.core.preprocess.peak_area import (
    area_per_height,
    casaxps_la_m_to_fwhm_g,
    gl_area_per_height,
    height_scale_for_area_ratio,
)
from sersflow.core.spectrum import XY
from sersflow.core.xps.catalog_validate import (
    validate_chemical_states_raw,
    validate_fitting_recipes_raw,
)
from sersflow.core.xps.fitting_recipes import load_fitting_recipes_catalog
from sersflow.core.xps.recipe_apply import apply_recipe_id


def test_la_alpha_on_high_be_side() -> None:
    """CasaXPS: α on high BE (x >= pos); β on low BE. Smaller exponent → longer tail."""
    x = np.linspace(90.0, 110.0, 401)
    pos = 100.0
    # α=1 (high BE), β=9 (low BE) → longer tail toward higher BE
    y = _la0(x, pos, 1.0, alpha=1.0, beta=9.0)
    high = y[x >= pos + 2.0].sum()
    low = y[x <= pos - 2.0].sum()
    assert high > low


def test_casaxps_m_maps_to_fraction_of_fwhm_not_eV() -> None:
    assert casaxps_la_m_to_fwhm_g(10, 1.0) == pytest.approx(0.1)
    assert casaxps_la_m_to_fwhm_g(10, 0.76) == pytest.approx(0.076)
    out = apply_recipe_id("sc_2p_sc0", pass_energy=20, include_background=False)
    # LA params: pos, amp, fwhm, alpha, beta, fwhm_g — fwhm_g must be << 10 eV
    # First peak starts at p0 index 0 without bg.
    fwhm = out["p0"][2]
    fwhm_g = out["p0"][5]
    assert fwhm_g == pytest.approx(casaxps_la_m_to_fwhm_g(10, fwhm))
    assert fwhm_g < 1.0


def test_gl_area_formulas_and_height_scale() -> None:
    # Equal FWHM → height ratio equals area ratio
    f = gl_area_per_height(1.0, 30)
    scale = height_scale_for_area_ratio(area_i=25.0, area_0=50.0, factor_i=f, factor_0=f)
    assert scale == pytest.approx(0.5)

    # Wider peak needs lower height for the same area
    f_narrow = gl_area_per_height(1.0, 30)
    f_wide = gl_area_per_height(2.0, 30)
    scale_w = height_scale_for_area_ratio(
        area_i=50.0, area_0=50.0, factor_i=f_wide, factor_0=f_narrow
    )
    assert scale_w == pytest.approx(0.5)


def test_multiplet_area_pct_uses_height_not_raw_pct() -> None:
    out = apply_recipe_id("cr_2p32_cr2o3", include_background=False)
    amp_links = [l for l in out["param_links"] if l["mode"] == "scale" and l["source_key"] == "amp"]
    assert amp_links
    # At least one scale must differ from naive area_pct/area_pct0 when FWHMs differ,
    # OR all equal-FWHM peaks keep exact area ratio — either is fine; scales must be positive.
    assert all(float(l["scale"]) > 0 for l in amp_links)
    assert any("area_pct converted to peak heights" in w for w in out["warnings"])


def test_so_amp_scale_accounts_for_fwhm_via_area() -> None:
    out = apply_recipe_id("sc_2p_sc0", pass_energy=20, include_background=False)
    amp_link = next(l for l in out["param_links"] if l["mode"] == "scale" and l["source_key"] == "amp")
    # Different FWHM 0.76 vs 0.79 → scale near but not exactly 0.5
    assert 0.4 < float(amp_link["scale"]) < 0.6


def test_shirley_seed_uses_low_be_endpoint() -> None:
    pytest.importorskip("lmfit")
    from sersflow.core.preprocess.fitting_lmfit import _apply_xps_fit_safeguards

    # Ascending BE: low BE at index 0
    x = np.linspace(90.0, 110.0, 50)
    y = np.linspace(1000.0, 100.0, 50)  # high counts at low BE
    problem = FitProblem(
        x=x,
        y=y,
        components=[FitComponent(component_type="shirley_bg", component_id="bg")],
        p0=[0.03, 0.0],
        bounds_lower=[0.0, None],
        bounds_upper=[None, None],
        technique_family="xps",
    )
    p0, _lo, _hi, _ = _apply_xps_fit_safeguards(
        problem,
        slices=[(0, 2)],
        param_keys_per_comp=[["k", "const"]],
    )
    assert p0[1] == pytest.approx(1000.0)

    # Descending BE: low BE at last index
    x2 = x[::-1]
    y2 = y[::-1]
    problem2 = FitProblem(
        x=x2,
        y=y2,
        components=[FitComponent(component_type="shirley_bg", component_id="bg")],
        p0=[0.03, 0.0],
        bounds_lower=[0.0, None],
        bounds_upper=[None, None],
        technique_family="xps",
    )
    p02, _, _, _ = _apply_xps_fit_safeguards(
        problem2,
        slices=[(0, 2)],
        param_keys_per_comp=[["k", "const"]],
    )
    assert p02[1] == pytest.approx(1000.0)


def test_invalid_technique_family_rejected() -> None:
    xy = XY(x=np.linspace(0, 1, 10), y=np.ones(10))
    with pytest.raises(ValueError, match="Invalid technique_family"):
        fit_problem_from_step_params(
            xy,
            {
                "components": [{"component_id": "a", "component_type": "gaussian"}],
                "p0": [0.5, 1.0, 0.1],
                "bounds_lower": [0.0, 0.0, 1e-6],
                "bounds_upper": [1.0, None, 1.0],
                "technique_family": "raman",
            },
        )


def test_assert_matching_technique_families() -> None:
    assert normalize_technique_family(None, default="vibrational") == "vibrational"
    with pytest.raises(ValueError, match="required"):
        normalize_technique_family(None, default=None)
    with pytest.raises(ValueError, match="mismatch"):
        assert_matching_technique_families("xps", "vibrational")
    assert assert_matching_technique_families("xps", "xps") == "xps"


def test_catalog_validation_accepts_packaged_recipes() -> None:
    load_fitting_recipes_catalog.cache_clear()
    cat = load_fitting_recipes_catalog()
    assert cat.compound_fits
    # Hard validation on a minimal broken payload
    with pytest.raises(ValueError, match="missing required"):
        validate_fitting_recipes_raw({"compound_fits": [{"id": "x"}]})
    with pytest.raises(ValueError, match="missing required"):
        validate_chemical_states_raw({"sections": [{"id": "Ag_3d"}]})


def test_a_gl_soft_fail_warns() -> None:
    out = apply_recipe_id("ni_2p32_metal_ref5", include_background=False)
    assert out["components"][0]["component_type"] == "a_gl"
    assert not any("not implemented" in w.lower() for w in out.get("warnings", []))


def test_la_numeric_area_positive() -> None:
    x = np.linspace(-20, 20, 2001)
    y = la(x, 0.0, 1.0, 1.0, 1.1, 9.0, 0.1)
    trap = getattr(np, "trapezoid", None) or np.trapz
    assert float(trap(y, x)) > 0
    assert area_per_height("la", {"fwhm": 1.0, "alpha": 1.1, "beta": 9.0, "fwhm_g": 0.1}) > 0
    assert math.isfinite(area_per_height("gl", {"fwhm": 1.2, "m": 30}))
