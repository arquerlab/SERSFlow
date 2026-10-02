from __future__ import annotations

import os

from fastapi.testclient import TestClient

from sersflow.core.xps.chemical_states import (
    list_chemical_state_entries,
    load_chemical_states_catalog,
)
from sersflow.core.xps.fitting_recipes import (
    list_compound_fits,
    list_method_defaults,
    load_fitting_recipes_catalog,
)


def test_full_catalog_loads() -> None:
    load_chemical_states_catalog.cache_clear()
    catalog = load_chemical_states_catalog()
    section_ids = {s.id for s in catalog.sections}
    assert "Ag_3d" in section_ids
    assert "Al_2p" in section_ids
    assert "C_1s" in section_ids
    assert "O_1s" in section_ids
    assert "Zr_3d" in section_ids
    assert len(catalog.sections) >= 100
    assert sum(len(s.entries) for s in catalog.sections) >= 2500
    assert "213-242" in str(catalog.source.get("handbook_pages", ""))


def test_handbook_provenance_backfill() -> None:
    load_chemical_states_catalog.cache_clear()
    ag = list_chemical_state_entries(element="Ag", line="3d", provenance="phi_handbook")
    assert len(ag) >= 30
    assert all(e.provenance == "phi_handbook" for e in ag)


def test_biesinger_literature_merged() -> None:
    load_chemical_states_catalog.cache_clear()
    ti = list_chemical_state_entries(
        element="Ti", line="2p3/2", provenance="biesinger_lit_compile"
    )
    assert len(ti) >= 3
    assert any(e.compound.startswith("Ti") for e in ti)

    cu = list_chemical_state_entries(element="Cu", provenance="biesinger_thesis")
    assert len(cu) >= 1


def test_ag_3d_and_al2p_lookups() -> None:
    load_chemical_states_catalog.cache_clear()
    ag3d = list_chemical_state_entries(element="Ag", line="3d")
    assert len(ag3d) >= 30
    assert any(e.compound == "Ag" and e.value_eV == 368.3 and "handbook" in e.references for e in ag3d)
    assert any(e.compound == "Ag2O" and e.value_eV == 367.8 for e in ag3d)

    ag2o = list_chemical_state_entries(element="Ag", line="3d", q="Ag2O")
    assert {e.value_eV for e in ag2o} >= {367.8, 368.4}

    al = list_chemical_state_entries(element="Al", line="2p", q="sapphire")
    assert any(e.compound == "Al2O3" and e.phase == "sapphire" and e.value_eV == 74.4 for e in al)

    mnn = list_chemical_state_entries(element="Ag", line="MNN")
    assert all(e.energy_kind == "kinetic" for e in mnn)
    assert any(e.compound == "Ag2Se" and e.value_eV == 351.4 for e in mnn)


def test_fitting_recipes_methods_and_sc_cr_ni() -> None:
    load_fitting_recipes_catalog.cache_clear()
    catalog = load_fitting_recipes_catalog()
    assert len(catalog.method_defaults) >= 4
    assert len(catalog.compound_fits) >= 100

    methods = list_method_defaults(chapter=2)
    assert len(methods) == 1
    assert methods[0].background == "shirley"
    assert methods[0].procedure_markdown
    assert any(c.get("id") == "c1s_co" for c in methods[0].constraints)

    sc = list_compound_fits(element="Sc", source_table="2.1")
    assert len(sc) >= 3
    metal = next(f for f in sc if "Sc(0)" in f.compound or f.compound == "Sc(0)")
    assert metal.peaks[0].get("lineshape", {}).get("casaxps") == "LA(1.1,9,10)"

    cr = list_compound_fits(element="Cr", source_table="3.1")
    assert len(cr) >= 5
    oxide = [f for f in cr if "Oxide" in f.compound or "Cr2O3" in f.compound or "Cr(III)" in f.compound]
    assert oxide
    assert sum(1 for f in oxide if len(f.peaks) >= 2) >= 1

    ni = list_compound_fits(element="Ni", q="NiO")
    assert len(ni) >= 1

    c1s = list_compound_fits(element="C", region="C_1s")
    assert len(c1s) >= 2
    core = next(f for f in c1s if f.id == "c_1s_adventitious")
    assert len(core.peaks) == 2
    assert core.peaks[0]["be_eV"] == 284.8
    assert core.peaks[0]["lineshape"]["casaxps"] == "GL(30)"
    assert core.peaks[1]["delta_eV"] == 1.5
    assert any("FWHM" in c for c in core.peaks[1]["constraints"])
    optional = next(f for f in c1s if f.id == "c_1s_adventitious_optional")
    labels = {p["label"] for p in optional.peaks}
    assert any("C=O" in lab for lab in labels)
    assert any("O-C=O" in lab for lab in labels)
    assert any("CO3" in lab for lab in labels)


def test_chemical_states_and_recipes_api() -> None:
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from sersflow.api.main import app

    client = TestClient(app)

    r = client.get("/xps/chemical-states", params={"element": "Ag", "line": "3d", "q": "Ag2O"})
    assert r.status_code == 200
    body = r.json()
    assert body["entry_count"] >= 2
    assert {e["value_eV"] for e in body["entries"]} >= {367.8, 368.4}

    r_prov = client.get(
        "/xps/chemical-states",
        params={"element": "Ti", "line": "2p3/2", "provenance": "biesinger_lit_compile"},
    )
    assert r_prov.status_code == 200
    assert r_prov.json()["entry_count"] >= 3

    r2 = client.get("/xps/fitting-recipes", params={"element": "Sc", "source_table": "2.1"})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["method_count"] >= 4
    assert body2["compound_fit_count"] >= 3
    assert any("procedure_markdown" in m and m["procedure_markdown"] for m in body2["method_defaults"])

    r3 = client.get("/xps/fitting-recipes", params={"element": "Cr", "source_table": "3.1", "include_methods": False})
    assert r3.status_code == 200
    assert r3.json()["method_count"] == 0
    assert r3.json()["compound_fit_count"] >= 5

    r_idx = client.get("/xps/fitting-recipes/index", params={"q": "Sc(0)", "limit": 10})
    assert r_idx.status_code == 200
    body_idx = r_idx.json()
    assert body_idx["count"] >= 1
    assert "peaks" not in body_idx["items"][0]
    assert "label" in body_idx["items"][0]

    rid = next(i["id"] for i in body_idx["items"] if "sc0" in i["id"] or "Sc(0)" in i["label"])
    r_apply = client.get(f"/xps/fitting-recipes/{rid}/apply", params={"pass_energy": 20})
    assert r_apply.status_code == 200
    applied = r_apply.json()
    assert applied["recipe_id"] == rid
    assert len(applied["components"]) >= 2
    assert "param_links" in applied
