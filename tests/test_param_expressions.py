"""F4: general relational constraint expressions, cycle detection, area terms, unbounded links."""

from __future__ import annotations

import os

import numpy as np
import pytest

from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.param_expressions import (
    expression_refs,
    parse_expression,
    remap_expression_ids,
    validate_param_links,
)
from sersflow.core.preprocess.peak_area import area_per_height
from sersflow.core.spectrum import XY

pytest.importorskip("lmfit")

X = np.linspace(770.0, 800.0, 900)


def _g(p: float, a: float, w: float) -> np.ndarray:
    return a * np.exp(-4.0 * np.log(2.0) * ((X - p) / w) ** 2)


Y = _g(778.0, 1000.0, 1.5) + _g(790.0, 600.0, 1.5) + _g(784.0, 300.0, 1.5) + np.random.default_rng(0).normal(0, 3, X.size)
COMPS = [{"component_id": c, "component_type": "gaussian"} for c in ("A", "B", "C")]


def _params(links: list[dict], c_pos_bounds: tuple[float, float] = (781.0, 787.0)) -> dict:
    return {
        "components": COMPS,
        "p0": [777.5, 900.0, 1.4, 790.5, 500.0, 1.4, 784.2, 200.0, 1.4],
        "bounds_lower": [775.0, 0.0, 0.5, 787.0, 0.0, 0.5, c_pos_bounds[0], 0.0, 0.5],
        "bounds_upper": [781.0, None, 4.0, 793.0, None, 4.0, c_pos_bounds[1], None, 4.0],
        "vary": [True] * 9,
        "technique_family": "xps",
        "param_links": links,
    }


def _fit(links: list[dict], **kw):
    return fit_curve(fit_problem_from_step_params(XY(x=X, y=Y), _params(links, **kw)))


def test_midpoint_expression_fits_correctly() -> None:
    """Gap doc F4 'done when': pos(C) = pos(A) + 0.5*(pos(B) - pos(A)) fits correctly."""
    r = _fit([{"source_component_id": "C", "source_key": "pos", "mode": "expr", "expr": "{A.pos} + 0.5*({B.pos} - {A.pos})"}])
    a, b, c = r.p_opt[0], r.p_opt[3], r.p_opt[6]
    assert c == pytest.approx(0.5 * (a + b), abs=1e-9)
    assert a == pytest.approx(778.0, abs=0.01) and b == pytest.approx(790.0, abs=0.01)
    assert np.isfinite(r.p_stderr[6]) and r.p_stderr[6] > 0  # F2 propagates through the expression


def test_cyclic_expressions_are_rejected_with_the_loop() -> None:
    """Gap doc F4 'done when': cyclic expressions are rejected with a clear error."""
    links = [
        {"source_component_id": "C", "source_key": "pos", "mode": "expr", "expr": "{B.pos} + 1"},
        {"source_component_id": "B", "source_key": "pos", "mode": "offset", "target_component_id": "C", "target_key": "pos", "offset": 2.0},
    ]
    with pytest.raises(ValueError, match=r"cyclic constraint: C\.pos -> B\.pos -> C\.pos"):
        _fit(links)
    three = [
        {"source_component_id": "A", "source_key": "fwhm", "mode": "expr", "expr": "{B.fwhm}"},
        {"source_component_id": "B", "source_key": "fwhm", "mode": "expr", "expr": "{C.fwhm}*1.1"},
        {"source_component_id": "C", "source_key": "fwhm", "mode": "equal", "target_component_id": "A", "target_key": "fwhm"},
    ]
    errs = validate_param_links(COMPS, three)
    assert len(errs) == 1 and errs[0].startswith("cyclic constraint:") and errs[0].count("->") == 3


def test_area_terms_on_both_sides() -> None:
    r = _fit(
        [{"source_component_id": "C", "source_key": "amp", "mode": "expr", "defines": "area", "expr": "0.25*({A.area} + {B.area})"}]
    )
    area = lambda i: r.p_opt[i + 1] * area_per_height("gaussian", {"fwhm": r.p_opt[i + 2]})  # noqa: E731
    assert area(6) / (area(0) + area(3)) == pytest.approx(0.25, rel=1e-9)
    r2 = _fit([{"source_component_id": "C", "source_key": "fwhm", "mode": "expr", "expr": "sqrt({A.fwhm}**2 + {B.fwhm}**2)"}])
    assert r2.p_opt[8] == pytest.approx(np.hypot(r2.p_opt[2], r2.p_opt[5]))


def test_linked_parameter_ignores_its_own_bounds() -> None:
    # C.pos bounds 783-785 would have clipped an offset of +12 (A at 778 -> 790) before F4.
    r = _fit(
        [{"source_component_id": "C", "source_key": "pos", "mode": "offset", "target_component_id": "A", "target_key": "pos", "offset": 12.0}],
        c_pos_bounds=(783.0, 785.0),
    )
    assert r.p_opt[6] - r.p_opt[0] == pytest.approx(12.0, abs=1e-9)


@pytest.mark.parametrize(
    "expr,msg",
    [
        ("__import__('os').system('x')", "not allowed"),
        ("{A.pos}.real", "not allowed"),
        ("{A.pos} if 1 else 2", "not allowed"),
        ("{A.pos} + q", "unknown name"),
        ("{A.pos} +", "syntax error"),
        ("lambda: 1", "not allowed"),
        ("{A.pos} // 2", "operator not allowed"),
        ("{A.pos", "malformed reference"),
        ("", "empty"),
    ],
)
def test_expression_whitelist(expr: str, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        parse_expression(expr)


def test_validation_messages() -> None:
    def errs(link: dict) -> list[str]:
        return validate_param_links(COMPS, [link])

    base = {"source_component_id": "C", "source_key": "pos", "mode": "expr"}
    assert "unknown component 'Z'" in errs({**base, "expr": "{Z.pos}"})[0]
    assert "has no parameter 'm'" in errs({**base, "expr": "{A.m}"})[0]
    assert "cannot depend on itself" in errs({**base, "expr": "{C.pos} + 1"})[0]
    assert "no {peak.param} reference" in errs({**base, "expr": "784.0"})[0]
    assert "defines=area needs" in errs({**base, "expr": "{A.area}", "defines": "area"})[0]
    dup = validate_param_links(COMPS, [{**base, "expr": "{A.pos}"}, {**base, "expr": "{B.pos}"}])
    assert dup == ["C.pos is defined by more than one link"]
    assert validate_param_links(COMPS, [{**base, "expr": "{A.pos} + 0.5*({B.pos} - {A.pos})"}]) == []


def test_ids_with_symbols_and_remapping() -> None:
    assert expression_refs("{Co3+.pos} - {2p3/2_sat.area}") == [("Co3+", "pos"), ("2p3/2_sat", "area")]
    assert remap_expression_ids("{A.pos} + {A.fwhm}*{B.pos}", {"A": "A_2"}) == "{A_2.pos} + {A_2.fwhm}*{B.pos}"


def test_recipe_merge_remaps_expression_ids() -> None:
    from sersflow.core.xps.recipe_apply import apply_recipe_id, merge_fitting_recipe_params

    base = apply_recipe_id("cl_2p_ircl3_hydrated", pass_energy=20)
    added = apply_recipe_id("cl_2p_ircl3_anhydrous", pass_energy=20, include_background=False)
    added["param_links"] = [
        *added["param_links"],
        {"source_component_id": "HCl_2p3_2", "source_key": "fwhm", "mode": "expr", "expr": "{IrCl_2p3_2.fwhm}*1.1"},
    ]
    added["param_links"] = [l for l in added["param_links"] if not (l["source_component_id"] == "HCl_2p3_2" and l["source_key"] == "fwhm" and l["mode"] != "expr")]
    merged = merge_fitting_recipe_params(base, added)
    ids = [c["component_id"] for c in merged["components"]]
    expr_links = [l for l in merged["param_links"] if l.get("mode") == "expr"]
    assert len(expr_links) == 1
    src = expr_links[0]["source_component_id"]
    ref = expression_refs(expr_links[0]["expr"])[0][0]
    assert src in ids and ref in ids and src != "HCl_2p3_2" and ref != "IrCl_2p3_2"  # both renamed on collision
    assert validate_param_links(merged["components"], merged["param_links"]) == []


def test_rest_validate_links() -> None:
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    c = TestClient(app)
    ok = c.post(
        "/fitting/validate-links",
        json={"components": COMPS, "param_links": [{"source_component_id": "C", "source_key": "pos", "mode": "expr", "expr": "{A.pos}+0.5*({B.pos}-{A.pos})"}]},
    ).json()
    assert ok == {"ok": True, "errors": [], "drivers": {"C.pos": ["A", "B"]}}
    bad = c.post(
        "/fitting/validate-links",
        json={
            "components": COMPS,
            "param_links": [
                {"source_component_id": "C", "source_key": "pos", "mode": "expr", "expr": "{B.pos}+1"},
                {"source_component_id": "B", "source_key": "pos", "mode": "expr", "expr": "{C.pos}-1"},
            ],
        },
    ).json()
    assert bad["ok"] is False and "cyclic" in bad["errors"][0]
