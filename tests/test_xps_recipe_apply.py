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
    modes = {(l["source_key"], l["mode"]) for l in out["param_links"]}
    assert ("pos", "offset") in modes
    assert ("fwhm", "equal") in modes
    # Amplitudes are seeded, not locked.
    assert ("amp", "scale") not in modes
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
    # Area ratios seed amplitudes only; no locked amp scale links.
    assert not any(l.get("source_key") == "amp" for l in out["param_links"])


def test_recipe_fwhm_fixed_amps_free() -> None:
    out = apply_recipe_id("co_2p32_co_oh2", pass_energy=20, include_background=False)
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    off = 0
    for comp in out["components"]:
        keys = [s.key for s in component_param_specs(comp["component_type"])]
        for k, vflag in zip(keys, out["vary"][off : off + len(keys)]):
            if k in {"fwhm", "fwhm_g", "fwhm_l"}:
                assert vflag is False, f"{comp['component_id']}.{k} should be fixed"
            if k == "amp":
                assert vflag is True, f"{comp['component_id']}.amp should vary"
        off += len(keys)
    assert not any(l.get("source_key") == "amp" for l in out["param_links"])
    assert any("FWHM" in w or "fwhm" in w.lower() for w in out.get("warnings") or [])
    ratios = out.get("initial_area_ratios")
    assert isinstance(ratios, str) and ":" in ratios
    parts = [float(p) for p in ratios.split(":")]
    assert len(parts) == len([c for c in out["components"] if c["component_type"] != "shirley_bg"])
    assert all(p > 0 for p in parts)


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


def test_unique_component_id_increments_trailing_number() -> None:
    from sersflow.core.xps.recipe_apply import unique_component_id

    used: set[str] = {"Peak_1", "Peak_2"}
    assert unique_component_id("Peak_1", used) == "Peak_3"
    assert unique_component_id("foo", used) == "foo"
    assert unique_component_id("foo", used) == "foo_2"


def test_merge_fitting_recipe_params_skips_second_baseline_and_renames() -> None:
    from sersflow.core.preprocess.fitting_specs import component_param_specs
    from sersflow.core.xps.recipe_apply import merge_fitting_recipe_params

    a = apply_recipe_id("sc_2p_sc0", pass_energy=20, include_background=True)
    b = apply_recipe_id("sc_2p_sc2o3", pass_energy=20, include_background=True)
    a_peak = next(c for c in a["components"] if c["component_type"] != "shirley_bg")
    b_peak = next(c for c in b["components"] if c["component_type"] != "shirley_bg")
    old_b_id = b_peak["component_id"]
    # Force a colliding peak id.
    b2 = dict(b)
    b2_comps = []
    for c in b["components"]:
        cc = dict(c)
        if cc["component_id"] == old_b_id:
            cc["component_id"] = a_peak["component_id"]
        b2_comps.append(cc)
    b2["components"] = b2_comps
    new_links = []
    for link in b.get("param_links") or []:
        ll = dict(link)
        if ll.get("source_component_id") == old_b_id:
            ll["source_component_id"] = a_peak["component_id"]
        if ll.get("target_component_id") == old_b_id:
            ll["target_component_id"] = a_peak["component_id"]
        new_links.append(ll)
    b2["param_links"] = new_links

    merged = merge_fitting_recipe_params(a, b2, skip_background_from_added=True)
    types = [c["component_type"] for c in merged["components"]]
    assert types.count("shirley_bg") == 1
    assert types[0] == "shirley_bg"
    assert len([t for t in types if t != "shirley_bg"]) == 4
    ids = [c["component_id"] for c in merged["components"]]
    assert len(ids) == len({i.lower() for i in ids})
    assert merged["recipe_ids"] == ["sc_2p_sc0", "sc_2p_sc2o3"]
    assert merged["recipe_id"] == "sc_2p_sc0"
    assert ids.count(a_peak["component_id"]) == 1
    assert any("renamed component" in w for w in merged.get("warnings") or [])
    known = set(ids)
    for link in merged.get("param_links") or []:
        assert link["source_component_id"] in known
        assert link["target_component_id"] in known
    n = sum(len(component_param_specs(c["component_type"])) for c in merged["components"])
    assert len(merged["p0"]) == n
    assert len(merged["bounds_lower"]) == n
    assert len(merged["bounds_upper"]) == n
    assert len(merged["vary"]) == n
