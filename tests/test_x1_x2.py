"""X1 (interactive fitting: evaluate-only preview, fit history) and X2 (identification helpers)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from sersflow.core.preprocess.fitting_models import gl

pytest.importorskip("lmfit")


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    return TestClient(app)


X = np.linspace(775, 795, 401)
Y = gl(X, 780.0, 1000.0, 1.6, 30) + gl(X, 785.0, 400.0, 2.4, 30) + 20.0


def _fit_request(p0, *, fit: bool = True, link: bool = False):
    # peak a: amp, pos, fwhm, m   (gl param order: amp, pos, fwhm, m via component_param_specs)
    comps = [
        {"component_id": "a", "component_type": "gl"},
        {"component_id": "b", "component_type": "gl"},
        {"component_id": "bg", "component_type": "linear_bg"},
    ]
    return {
        "target": {"kind": "inline", "x": X.tolist(), "y": Y.tolist()},
        "components": comps,
        "p0": p0,
        "bounds": {"lower": [None] * len(p0), "upper": [None] * len(p0)},
        "technique_family": "xps",
        "fit": fit,
        "return_curve": True,
        "weighting": "none",
    }


def _spec_keys(api, ct):
    models = api.get("/fitting/models").json()
    for m in models.get("models", models.get("items", [])):
        if m.get("component_type") == ct or m.get("id") == ct:
            return [p["key"] for p in m["params"]]
    raise AssertionError(f"model {ct} not listed")


def test_evaluate_only_draws_the_model_at_the_given_parameters(api) -> None:
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    ka = [s.key for s in component_param_specs("gl")]
    kb = [s.key for s in component_param_specs("linear_bg")]
    pa = {"amp": 900.0, "pos": 780.4, "fwhm": 1.9, "m": 30.0}
    pb = {"amp": 350.0, "pos": 785.3, "fwhm": 2.2, "m": 30.0}
    p0 = [pa[k] for k in ka] + [pb[k] for k in ka] + [20.0 for _ in kb]
    r = api.post("/fitting/fit", json=_fit_request(p0, fit=False))
    assert r.status_code == 200, r.text
    out = r.json()
    # no refit: parameters come back exactly as sent (peak params), curve equals the model at those values
    got = {c["component_id"]: c["params"] for c in out["components"]}
    assert got["a"]["pos"] == pytest.approx(780.4) and got["b"]["fwhm"] == pytest.approx(2.2)
    expect = gl(X, 780.4, 900.0, 1.9, 30) + gl(X, 785.3, 350.0, 2.2, 30) + 20.0
    assert np.allclose(np.asarray(out["y_hat"]), expect, atol=1e-6) or np.corrcoef(np.asarray(out["y_hat"]), expect)[0, 1] > 0.999
    # the same request with fit=true moves the position towards the truth
    fitted = api.post("/fitting/fit", json=_fit_request(p0, fit=True)).json()
    pos = {c["component_id"]: c["params"]["pos"] for c in fitted["components"] if "pos" in c["params"]}
    assert abs(pos["a"] - 780.0) < 0.05 < abs(got["a"]["pos"] - 780.0)


def _step_params(pos=780.0):
    return {
        "components": [{"component_id": "a", "component_type": "gl"}, {"component_id": "bg", "component_type": "linear_bg"}],
        "p0": [pos, 1000.0, 1.6, 30.0, 20.0, 20.0],
        "bounds_lower": [None, 0.0, 0.2, 0.0, None, None],
        "bounds_upper": [None, None, 10.0, 100.0, None, None],
        "vary": [True, True, True, False, False, False],
        "fit_min_x": 776.0,
        "fit_max_x": 790.0,
    }


def test_fit_history_store_dedupe_pin_cap_and_compare(api) -> None:
    scope = "ds1|Co2p|step3"
    a = api.post("/fitting/history", json={"scope_key": scope, "params": _step_params(), "summary": {"redchi": 2.0, "rmse": 5.0}}).json()
    assert a["created"] is True and len(a["params_hash"]) == 64
    # same state again: no new row, summary refreshed
    again = api.post("/fitting/history", json={"scope_key": scope, "params": _step_params(), "summary": {"redchi": 1.5}}).json()
    assert again["created"] is False and again["history_id"] == a["history_id"] and again["summary"]["redchi"] == 1.5
    b = api.post("/fitting/history", json={"scope_key": scope, "params": _step_params(pos=780.6), "summary": {"redchi": 1.1}}).json()
    assert b["created"] is True
    named = api.post("/fitting/history", json={"scope_key": scope, "params": _step_params(pos=781.0), "label": "good one"}).json()
    assert named["pinned"] is True and named["label"] == "good one"
    lst = api.get("/fitting/history", params={"scope_key": scope}).json()
    assert lst["count"] == 3 and lst["items"][0]["history_id"] == named["history_id"]  # newest first
    # other scope is isolated
    assert api.get("/fitting/history", params={"scope_key": "other"}).json()["count"] == 0

    cmp_ = api.get("/fitting/history/compare", params={"a": a["history_id"], "b": b["history_id"]}).json()
    pos_row = next(r for r in cmp_["rows"] if r["component_id"] == "a" and r["key"] == "pos")
    assert pos_row["a"] == 780.0 and pos_row["b"] == 780.6 and pos_row["delta"] == pytest.approx(0.6)
    assert cmp_["window_a"] == [776.0, 790.0]
    assert any(s["name"] == "redchi" and s["b"] == 1.1 for s in cmp_["stats"])
    assert not any(s["name"] == "fitted" for s in cmp_["stats"])  # booleans are not statistics

    # RESET drops unpinned snapshots only
    cleared = api.delete("/fitting/history", params={"scope_key": scope}).json()
    assert cleared["deleted"] == 2
    left = api.get("/fitting/history", params={"scope_key": scope, "include_params": False}).json()
    assert [i["label"] for i in left["items"]] == ["good one"] and "params" not in left["items"][0]
    assert api.delete(f"/fitting/history/{named['history_id']}").json() == {"deleted": True}
    assert api.get(f"/fitting/history/{named['history_id']}").status_code == 404
    assert api.post("/fitting/history", json={"scope_key": scope, "params": {"components": []}}).status_code == 400


def test_fit_history_caps_unpinned(api) -> None:
    from sersflow.infra.fit_history_store import MAX_UNPINNED

    scope = "cap"
    for i in range(MAX_UNPINNED + 5):
        api.post("/fitting/history", json={"scope_key": scope, "params": _step_params(pos=780.0 + i * 0.01)})
    n = api.get("/fitting/history", params={"scope_key": scope, "include_params": False, "limit": 500}).json()["count"]
    assert n == MAX_UNPINNED


# ------------------------------------------------------------------------------------------------ X2


def test_line_markers_derived_from_chemical_states() -> None:
    from sersflow.core.xps.line_markers import element_line_markers, reference_markers

    m = element_line_markers(be_min=770, be_max=800)
    co = next(x for x in m["markers"] if x["element"] == "Co")
    assert co["line"] == "2p" and co["basis"] == "elemental" and 777.5 < co["be_eV"] < 779.0
    assert co["be_min_eV"] <= co["be_eV"] <= co["be_max_eV"] and m["note"]
    allm = element_line_markers()
    assert not any("split" in x["line"].lower() for x in allm["markers"])  # splittings are not binding energies
    assert allm["auger_skipped_no_photon_energy"] > 0 and all(x["kind"] == "core" for x in allm["markers"])
    withhv = element_line_markers(photon_energy_eV=1486.6, element="Au")
    auger = [x for x in withhv["markers"] if x["kind"] == "auger"]
    assert auger and abs(auger[0]["be_eV"] + auger[0]["ke_eV"] - 1486.6) < 1e-6
    # grouped chemical states of Co 2p: metal, CoO and Co3O4 are present with spread info
    ref = reference_markers("Co", "2p")
    by = {c["compound"]: c for c in ref["compounds"]}
    assert {"Co", "CoO", "Co3O4"} <= set(by)
    assert by["Co"]["elemental"] is True and by["Co"]["n_entries"] >= 1
    assert by["Co"]["median_eV"] < by["CoO"]["median_eV"] < 783
    assert by["CoO"]["min_eV"] <= by["CoO"]["median_eV"] <= by["CoO"]["max_eV"] and by["CoO"]["provenance"]


def _survey():
    x = np.linspace(1100, 0, 5501)  # descending BE, 0.2 eV step
    y = 50.0 + 20.0 * np.exp(-(x - 500.0) / 600.0)  # sloping background
    for pos, amp in ((284.5, 800.0), (531.0, 2500.0), (778.3, 1500.0), (84.0, 600.0)):
        y = y + amp * np.exp(-0.5 * ((x - pos) / 0.9) ** 2)
    rng = np.random.default_rng(3)
    return x, y + rng.normal(0, 4.0, x.size)


def test_survey_peak_detection_matches_library_lines(api) -> None:
    x, y = _survey()
    r = api.post("/xps/survey/detect", json={"x": x.tolist(), "y": y.tolist(), "prominence_pct": 5.0}).json()
    found = {round(p["be_eV"]): p for p in r["peaks"]}
    for be, label in ((285, "C 1s"), (531, "O 1s"), (778, "Co 2p"), (84, "Au 4f")):
        near = [p for k, p in found.items() if abs(k - be) <= 1]
        assert near, (be, sorted(found))
        assert near[0]["match"] is not None and near[0]["match"]["label"] == label, (be, near[0]["match"])
        assert near[0]["match"]["in_library_range"] is True
        if near[0]["match"]["basis"] == "elemental":
            assert abs(near[0]["match"]["delta_eV"]) < 1.5
    assert r["count"] == len(r["peaks"]) and r["count"] <= 60
    # unmatched noise stays unmatched; ascending input works the same
    asc = api.post("/xps/survey/detect", json={"x": x[::-1].tolist(), "y": y[::-1].tolist(), "prominence_pct": 5.0}).json()
    assert [round(p["be_eV"]) for p in asc["peaks"]] == sorted(round(p["be_eV"]) for p in r["peaks"])
    assert api.post("/xps/survey/detect", json={"x": [1, 2], "y": [1, 2]}).status_code == 422


def test_region_sets_crud_csv_and_validation(api) -> None:
    regs = [
        {"element": "C", "line": "1s", "be_eV": 285.0, "be_min_eV": 275.0, "be_max_eV": 295.0},
        {"element": "O", "line": "1s", "be_min_eV": 520.0, "be_max_eV": 540.0},
    ]
    r = api.post("/xps/region-sets", json={"name": "survey A", "regions": regs, "source": {"dataset_id": "ds"}}).json()
    assert r["n_regions"] == 2 and r["regions"][1]["be_eV"] == 530.0 and r["regions"][1]["label"] == "O 1s"
    assert api.get("/xps/region-sets").json()["count"] == 1
    csv_text = api.get(f"/xps/region-sets/{r['set_id']}", params={"format": "csv"}).text
    lines = csv_text.strip().splitlines()
    assert lines[0] == "label,element,line,be_eV,be_min_eV,be_max_eV,width_eV" and lines[1].endswith(",20.0")
    bad = api.post("/xps/region-sets", json={"name": "x", "regions": [{"be_min_eV": 5, "be_max_eV": 4}]})
    assert bad.status_code == 400
    assert api.delete(f"/xps/region-sets/{r['set_id']}").json() == {"deleted": True}
    assert api.get(f"/xps/region-sets/{r['set_id']}").status_code == 404
