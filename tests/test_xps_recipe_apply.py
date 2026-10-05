from __future__ import annotations

import pytest

from sersflow.core.xps.fitting_recipes import (
    get_compound_fit,
    list_compound_fit_index,
    list_compound_fits,
    load_fitting_recipes_catalog,
)
from sersflow.core.xps.recipe_apply import apply_recipe_id


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> None:
    load_fitting_recipes_catalog.cache_clear()


def test_list_compound_fits_q_matches_element_and_id() -> None:
    by_el = list_compound_fits(q="sc_2p")
    assert any(f.id == "sc_2p_sc0" for f in by_el)
    by_id = list_compound_fits(q="sc_2p_sc0")
    assert len(by_id) >= 1
    assert by_id[0].id == "sc_2p_sc0"


def test_compound_fit_index_omits_peaks_and_respects_limit() -> None:
    items = list_compound_fit_index(limit=5)
    assert len(items) == 5
    assert "peaks" not in items[0]
    assert "label" in items[0]
    assert items[0]["id"]


def test_get_compound_fit() -> None:
    fit = get_compound_fit("sc_2p_sc0")
    assert fit is not None
    assert fit.compound.startswith("Sc")


def test_apply_sc0_la_so_links() -> None:
    out = apply_recipe_id("sc_2p_sc0", pass_energy=20, include_background=True)
    types = [c["component_type"] for c in out["components"]]
    assert types[0] == "shirley_bg"
    assert types[1:] == ["la", "la"]
    assert out["recipe_pass_energy"] == 20
    assert out["xps_region"] == "Sc2p"
    modes = { (l["source_key"], l["mode"]) for l in out["param_links"] }
    assert ("pos", "offset") in modes
    assert ("amp", "scale") in modes
    assert ("fwhm", "equal") in modes
    offset_link = next(l for l in out["param_links"] if l["mode"] == "offset")
    assert abs(float(offset_link["offset"]) - 4.74) < 1e-6


def test_apply_sc2o3_gl_m() -> None:
    out = apply_recipe_id("sc_2p_sc2o3", pass_energy=10, include_background=False)
    assert all(c["component_type"] == "gl" for c in out["components"])
    # GL params: pos, amp, fwhm, m — m should be 59 for PE 10
    assert 59.0 in out["p0"]


def test_apply_multiplet_cr2o3() -> None:
    out = apply_recipe_id("cr_2p32_cr2o3", include_background=False)
    assert len(out["components"]) == 5
    assert any(l["mode"] == "offset" for l in out["param_links"])
    assert any(l["mode"] == "scale" for l in out["param_links"])


def test_apply_fermi_edge_valence_recipe() -> None:
    by_q = list_compound_fits(q="Fermi")
    assert any(f.id == "fermi_edge_valence" for f in by_q)
    out = apply_recipe_id("fermi_edge_valence")
    assert out["components"] == [{"component_id": "Fermi_edge", "component_type": "fermi_edge"}]
    # amplitude, center, sigma, temperature_K, const
    assert out["p0"] == [0.0, 0.0, 0.25, 298.0, 0.0]
    assert out["bounds_lower"] == [0.0, -3.0, 0.05, None, 0.0]
    assert out["bounds_upper"] == [1.0e7, 3.0, 0.4, None, 1.0e7]
    assert out["vary"] == [True, True, True, False, True]
    assert out.get("param_links") == []
    assert out.get("recipe_pass_energy") is None
    assert out.get("xps_region") == "all valence bands"
    assert "shirley_bg" not in [c["component_type"] for c in out["components"]]


def test_apply_invalid_pass_energy() -> None:
    with pytest.raises(ValueError, match="pass_energy"):
        apply_recipe_id("sc_2p_sc0", pass_energy=99)


def test_c1s_adventitious_searchable_and_apply_links() -> None:
    by_alias = list_compound_fits(q="C1s")
    assert any(f.id == "c_1s_adventitious" for f in by_alias)
    by_space = list_compound_fits(q="C 1s")
    assert any(f.id == "c_1s_adventitious" for f in by_space)
    by_adv = list_compound_fits(q="adventitious")
    assert any(f.id == "c_1s_adventitious" for f in by_adv)

    idx = list_compound_fit_index(q="C1s", limit=20)
    assert any(it["id"] == "c_1s_adventitious" for it in idx)
    hit = next(it for it in idx if it["id"] == "c_1s_adventitious")
    assert "C1s" in (hit.get("aliases") or [])

    out = apply_recipe_id("c_1s_adventitious", pass_energy=20, include_background=True)
    assert out["components"][0]["component_type"] == "shirley_bg"
    assert [c["component_type"] for c in out["components"][1:]] == ["gl", "gl"]
    assert out["xps_region"] == "C1s"
    pos_links = [l for l in out["param_links"] if l["mode"] == "offset" and l["source_key"] == "pos"]
    assert pos_links
    assert abs(float(pos_links[0]["offset"]) - 1.5) < 1e-9
    assert any(l["mode"] == "equal" and l["source_key"] == "fwhm" for l in out["param_links"])
