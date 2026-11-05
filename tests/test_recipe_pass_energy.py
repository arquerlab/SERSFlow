"""K3: recipe pass-energy column fallback is reported as a structured warning on every surface."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from sersflow.core.xps.fitting_recipes import CompoundFit, load_fitting_recipes_catalog
from sersflow.core.xps.recipe_apply import apply_compound_fit_to_fitting_params, apply_recipe_id


def _fit(pass_energies=(10, 20), peaks=None) -> CompoundFit:
    peaks = peaks or (
        {"label": "A", "be_eV": 780.0, "fwhm_10": 1.1, "fwhm_20": 1.4, "lineshape": {"kind": "gl", "m": 30}},
        {"label": "B", "be_eV": 782.0, "fwhm_10": 1.2, "lineshape": {"kind": "gl", "m": 30}},
    )
    return CompoundFit(
        id="t_fit",
        element="Co",
        region="Co_2p",
        compound="test",
        source_table=None,
        pdf_page=None,
        pass_energies=tuple(pass_energies),
        peaks=tuple(peaks),
        footnotes=(),
        raw={},
    )


def test_exact_column_has_no_fallback() -> None:
    out = apply_compound_fit_to_fitting_params(_fit(), pass_energy=10, include_background=False)
    res = out["pass_energy_resolution"]
    assert res["used"] == 10 and res["source"] == "request"
    assert res["fallback"] is False
    assert res["fwhm_fallbacks"] == []
    assert not any(w.startswith("pass energy:") for w in out["warnings"])


def test_missing_peak_column_is_structured_and_single_warning() -> None:
    out = apply_compound_fit_to_fitting_params(_fit(), pass_energy=20, include_background=False)
    res = out["pass_energy_resolution"]
    assert res["fallback"] is True
    assert res["fwhm_fallbacks"] == [{"peak": "B", "requested_column": "fwhm_20", "used_column": "fwhm_10"}]
    pe_warnings = [w for w in out["warnings"] if w.startswith("pass energy:")]
    assert len(pe_warnings) == 1
    assert "fwhm_20" in pe_warnings[0] and "fwhm_10" in pe_warnings[0]


def test_unsupported_acquisition_pe_reports_closest_column() -> None:
    out = apply_compound_fit_to_fitting_params(
        _fit(), preferred_pass_energy=50, include_background=False
    )
    res = out["pass_energy_resolution"]
    assert res["acquisition"] == 50
    assert res["used"] == 20
    assert res["source"] == "acquisition_closest"
    assert res["available"] == [10, 20]
    assert res["fallback"] is True
    assert any("50 eV" in w for w in out["warnings"] if w.startswith("pass energy:"))


def test_no_fwhm_column_at_all_defaults_to_one() -> None:
    peaks = ({"label": "A", "be_eV": 780.0, "lineshape": {"kind": "gl", "m": 30}},)
    out = apply_compound_fit_to_fitting_params(_fit(peaks=peaks), pass_energy=20, include_background=False)
    fb = out["pass_energy_resolution"]["fwhm_fallbacks"]
    assert fb == [{"peak": "A", "requested_column": "fwhm_20", "used_column": None}]
    assert any("1.0 eV" in w for w in out["warnings"])


def test_packaged_recipe_unsupported_pe_is_flagged() -> None:
    load_fitting_recipes_catalog.cache_clear()
    out = apply_recipe_id("cu_2p32_cuo", preferred_pass_energy=50, include_background=False)
    res = out["pass_energy_resolution"]
    assert res["source"] == "acquisition_closest" and res["used"] == 20 and res["fallback"] is True


def test_rest_apply_returns_pass_energy_resolution() -> None:
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from sersflow.api.main import app

    client = TestClient(app)
    r = client.get("/xps/fitting-recipes/cu_2p32_cuo/apply", params={"preferred_pass_energy": 50})
    assert r.status_code == 200, r.text
    res = r.json()["pass_energy_resolution"]
    assert res["source"] == "acquisition_closest"
    assert res["fallback"] is True
    assert res["acquisition"] == 50


def test_mcp_recipe_tools_return_pass_energy_resolution(tmp_path: Path) -> None:
    from tests.sersflow_mcp.test_tool_handlers import _ready_ctx, _tool_fn
    from sersflow.mcp.server import create_server

    applied = apply_compound_fit_to_fitting_params(
        _fit(), preferred_pass_energy=50, include_background=False
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/apply"):
            return httpx.Response(200, json=applied)
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    raw = asyncio.run(_tool_fn(mcp, "apply_xps_fitting_recipe")(recipe_id="t_fit", preferred_pass_energy=50))
    data = json.loads(raw)
    assert data["data"]["pass_energy_resolution"]["source"] == "acquisition_closest"

    raw2 = asyncio.run(
        _tool_fn(mcp, "post_xps_apply_recipe_to_pipeline_draft")(
            recipe_id="t_fit", preferred_pass_energy=50, confirm=True
        )
    )
    data2 = json.loads(raw2)
    assert data2["pass_energy_resolution"]["fallback"] is True
    assert any(w.startswith("pass energy:") for w in data2["warnings"])
