"""Robustness study core: design, patches, ANOVA exactness, per-cell fit, aggregation."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from sersflow.core.robustness import anova
from sersflow.core.robustness.cell_fit import common_window, fit_cell
from sersflow.core.robustness.design import DesignError, build_design, estimate_cost
from sersflow.core.robustness.patches import apply_fit_patches, split_patches
from sersflow.core.robustness.responses import ResponseError, evaluate_responses, trend_metrics, validate_responses
from sersflow.core.robustness.study import apply_filter, summarize_study
from sersflow.core.spectrum import XY

pytest.importorskip("lmfitxps")


# ------------------------------------------------------------------ fixtures


def _gl(x, pos, area_scale, fwhm):
    s = fwhm / 2.355
    return area_scale * np.exp(-((x - pos) ** 2) / (2 * s**2))


def _spectrum(seed=0, frac2=0.4, noise=20.0, delta=1.8):
    """Two overlapping peaks on a Shirley-ish background, descending BE axis."""
    rng = np.random.default_rng(seed)
    x = np.linspace(790.0, 772.0, 361)
    p1 = _gl(x, 780.0, 3000.0 * (1 - frac2), 1.4)
    p2 = _gl(x, 780.0 + delta, 3000.0 * frac2, 1.4)
    cum = np.cumsum((p1 + p2)[::-1])[::-1]
    bg = 500.0 + 300.0 * cum / cum[0]
    y = bg + p1 + p2 + rng.normal(0.0, noise, x.shape)
    return XY(x=x, y=y)


def _base_params():
    return {
        "technique_family": "xps",
        "fit_min_x": 772.0,
        "fit_max_x": 790.0,
        "components": [
            {"component_id": "bg", "component_type": "shirley_bg"},
            {"component_id": "A", "component_type": "gaussian"},
            {"component_id": "B", "component_type": "gaussian"},
        ],
        # shirley_bg: k, const | gaussian: pos, amp, fwhm
        "p0": [0.03, 500.0, 780.0, 1500.0, 1.4, 781.8, 1000.0, 1.4],
        "bounds_lower": [0.0, None, 779.0, 0.0, 0.5, 781.0, 0.0, 0.5],
        "bounds_upper": [None, None, 781.0, None, 3.0, 783.0, None, 3.0],
        "vary": [True] * 8,
    }


RESPONSES = [
    {"name": "B_pct", "kind": "area_pct", "component_id": "B"},
    {"name": "B_pos", "kind": "param", "component_id": "B", "key": "pos"},
    {"name": "B_frac", "kind": "group_fraction", "numerator": ["B"], "denominator": ["A", "B"]},
]

FACTORS = [
    {
        "name": "background",
        "levels": [
            {"name": "shirley", "patches": []},
            {"name": "linear", "patches": [{"op": "swap_component_type", "select": {"component_ids": ["bg"]}, "new_type": "linear_bg"}]},
        ],
    },
    {
        "name": "window",
        "levels": [
            {"name": "wide", "patches": []},
            {"name": "narrow", "patches": [
                {"op": "set_step_param", "key": "fit_min_x", "value": 775.0},
                {"op": "set_step_param", "key": "fit_max_x", "value": 788.0},
            ]},
        ],
    },
    {
        "name": "fwhm",
        "levels": [
            {"name": "free", "patches": []},
            {"name": "tied", "patches": [{"op": "tie_param", "select": {"role": "peaks"}, "key": "fwhm"}]},
        ],
    },
]


# ------------------------------------------------------------------ design


def test_design_full_factorial_and_hash_is_deterministic():
    d1 = build_design(FACTORS)
    d2 = build_design(FACTORS)
    assert len(d1.cells) == 8 and d1.exact and d1.n_full == 8
    assert d1.design_hash() == d2.design_hash()
    assert len({c.cell_id for c in d1.cells}) == 8
    assert d1.n_upstream_groups() == 1


def test_design_cap_refuses_instead_of_thinning():
    with pytest.raises(DesignError, match="max_cells"):
        build_design(FACTORS, max_cells=4)
    assert len(build_design(FACTORS, max_cells=None).cells) == 8


def test_design_subsample_is_opt_in_and_marked_inexact():
    d = build_design(FACTORS, subsample={"n": 5, "seed": 1})
    assert len(d.cells) == 5 and not d.exact
    d_b = build_design(FACTORS, subsample={"n": 5, "seed": 1})
    assert [c.cell_id for c in d.cells] == [c.cell_id for c in d_b.cells]
    assert [c.level_index for c in d.cells] == [c.level_index for c in d_b.cells]


def test_design_rejects_bad_specs():
    with pytest.raises(DesignError):
        build_design([])
    with pytest.raises(DesignError):
        build_design([{"name": "a", "levels": ["only-one"]}])
    with pytest.raises(DesignError):
        build_design([{"name": "a", "levels": [{"name": "x", "patches": [{"op": "nope"}]}, "y"]}])


def test_upstream_cells_group_by_signature():
    d = build_design(
        [
            {"name": "baseline", "levels": [
                {"name": "off", "patches": []},
                {"name": "als", "patches": [{"op": "set_step_param", "target": {"step_name": "baseline"}, "key": "method", "value": "als"}]},
            ]},
            FACTORS[1],
        ]
    )
    assert d.n_upstream_groups() == 2
    assert all(len(c.upstream_patches) == (1 if c.levels[0] == "als" else 0) for c in d.cells)


def test_estimate_cost():
    e = estimate_cost(n_cells=100, n_spectra=12, n_starts=5, n_upstream_groups=2, noise_replicates=50)
    assert e["n_fits"] == 6000 and e["n_noise_fits"] == 600 and e["n_total_fits"] == 6600


# ------------------------------------------------------------------ patches


def test_swap_drop_tie_keep_vectors_consistent():
    base = _base_params()
    out = apply_fit_patches(base, [{"op": "swap_component_type", "select": {"role": "background"}, "new_type": "linear_bg"}])
    assert out["components"][0]["component_type"] == "linear_bg"
    assert len(out["p0"]) == 2 + 3 + 3 and len(out["vary"]) == 8
    # input untouched
    assert base["components"][0]["component_type"] == "shirley_bg"

    out = apply_fit_patches(base, [{"op": "drop_components", "select": {"component_ids": ["B"]}}])
    assert [c["component_id"] for c in out["components"]] == ["bg", "A"]
    assert len(out["p0"]) == 5

    out = apply_fit_patches(base, [{"op": "tie_param", "select": {"role": "peaks"}, "key": "fwhm"}])
    assert out["param_links"] == [
        {"source_component_id": "B", "source_key": "fwhm", "target_component_id": "A", "target_key": "fwhm", "mode": "equal"}
    ]
    assert out["vary"][7] is False
    out2 = apply_fit_patches(out, [{"op": "untie_param", "key": "fwhm"}])
    assert out2["param_links"] == [] and out2["vary"][7] is True


def test_set_component_param_widens_bounds_and_fixes():
    base = _base_params()
    out = apply_fit_patches(
        base, [{"op": "set_component_param", "select": {"component_type": "gaussian"}, "key": "fwhm", "value": 2.0, "vary": False}]
    )
    assert out["p0"][4] == 2.0 and out["p0"][7] == 2.0
    assert out["vary"][4] is False and out["vary"][7] is False
    with pytest.raises(ValueError):
        apply_fit_patches(base, [{"op": "set_component_param", "select": {"component_ids": ["bg"]}, "key": "fwhm", "value": 1}])


def test_upstream_patch_cannot_use_fit_only_ops():
    with pytest.raises(ValueError):
        split_patches([{"op": "tie_param", "target": {"step_name": "baseline"}, "key": "fwhm"}])


# ------------------------------------------------------------------ ANOVA


def _grid(levels):
    return list(itertools.product(*[range(n) for n in levels]))


def test_anova_exact_on_known_additive_plus_interaction():
    L = [3, 2, 2]
    idx = _grid(L)
    a, b, c = np.array([0.0, 1.0, 3.0]), np.array([0.0, 2.0]), np.array([0.0, 0.5])
    y = [a[i] + b[j] + c[k] + 1.5 * (i == 2) * (j == 1) for i, j, k in idx]
    res = anova.decompose(idx, y, L, ["A", "B", "C"])
    assert res["exact"]
    shares = {t["term"]: t["share"] for t in res["terms"]}
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-9)
    # C has no interactions: its share is its marginal SS / total
    yy = np.array(y)
    total = np.sum((yy - yy.mean()) ** 2)
    ss_c = len(y) / 2 * sum((np.mean([v for v, (_, _, k2) in zip(y, idx) if k2 == k]) - yy.mean()) ** 2 for k in (0, 1))
    assert shares["C"] == pytest.approx(ss_c / total, rel=1e-9)
    assert shares["A x C"] == pytest.approx(0.0, abs=1e-12) and shares["A x B x C"] == pytest.approx(0.0, abs=1e-12)
    assert shares["A x B"] > 0.0


def test_anova_pure_main_effect_has_no_other_share():
    L = [2, 3]
    idx = _grid(L)
    y = [10.0 * i for i, j in idx]
    res = anova.decompose(idx, y, L, ["A", "B"])
    shares = {t["term"]: t["share"] for t in res["terms"]}
    assert shares["A"] == pytest.approx(1.0) and shares["B"] == pytest.approx(0.0, abs=1e-12)


def test_anova_order_truncation_pools_remainder():
    L = [2, 2, 2]
    idx = _grid(L)
    y = [float(i * j * k) for i, j, k in idx]  # pure three-way structure plus lower-order parts
    res = anova.decompose(idx, y, L, ["A", "B", "C"], max_order=1)
    assert any(t["term"] == "higher-order" for t in res["terms"])
    assert sum(t["share"] for t in res["terms"]) == pytest.approx(1.0, abs=1e-9)


def test_anova_missing_cells_flagged_inexact_and_close():
    L = [3, 2]
    idx = _grid(L)
    y = [float(2 * i + 0.5 * j) for i, j in idx]
    y[2] = None
    res = anova.decompose(idx, y, L, ["A", "B"])
    assert not res["exact"] and res["n_obs"] == 5
    shares = {t["term"]: t["share"] for t in res["terms"]}
    assert shares["A"] > 0.9


def test_anova_zero_variance_gives_no_share():
    res = anova.decompose(_grid([2, 2]), [1.0] * 4, [2, 2], ["A", "B"])
    assert all(t["share"] is None for t in res["terms"])


# ------------------------------------------------------------------ responses


def test_responses_validate_and_evaluate():
    with pytest.raises(ResponseError):
        validate_responses([{"name": "x", "kind": "area_pct"}])
    xy = _spectrum()
    rec = fit_cell(xy, _base_params(), [], spectrum_id="s", cell_id="c", responses=RESPONSES)
    assert rec["error"] is None
    r = rec["responses"]
    assert r["B_frac"] == pytest.approx(r["B_pct"] / 100.0, rel=1e-6)
    # evaluated again from the stored fit
    again = evaluate_responses(RESPONSES, rec["mapping"], np.asarray(rec["p_opt"]))
    assert again["B_pct"] == pytest.approx(r["B_pct"])
    # missing component -> None, not an exception
    assert evaluate_responses([{"name": "z", "kind": "area_pct", "component_id": "ZZ"}], rec["mapping"], np.asarray(rec["p_opt"])) == {"z": None}


def test_trend_metrics():
    t = trend_metrics(np.array([1.0, 2.0, 3.0, 4.0]), np.array([0.1, 0.3, 0.35, 0.9]))
    assert t["sign"] == 1.0 and t["spearman"] == pytest.approx(1.0)


# ------------------------------------------------------------------ cell fit


def test_fit_cell_recovers_truth_and_is_deterministic():
    xy = _spectrum(frac2=0.4, noise=10.0)
    a = fit_cell(xy, _base_params(), [], spectrum_id="s1", cell_id="c0", responses=RESPONSES, n_starts=3, seed=7)
    b = fit_cell(xy, _base_params(), [], spectrum_id="s1", cell_id="c0", responses=RESPONSES, n_starts=3, seed=7)
    assert a["error"] is None
    assert a["responses"]["B_frac"] == pytest.approx(0.4, abs=0.06)
    assert a["start_chi2"] == b["start_chi2"] and a["responses"] == b["responses"]
    assert a["n_starts"] == 3 and a["n_starts_ok"] >= 1


def test_fit_cell_reports_failure_not_exception():
    rec = fit_cell(_spectrum(), _base_params(), [{"op": "drop_components", "select": {"component_ids": ["nope"]}}],
                   spectrum_id="s", cell_id="c", responses=RESPONSES)
    assert rec["error"]


def test_common_window_is_intersection_and_scores_are_comparable():
    d = build_design(FACTORS)
    base = _base_params()
    win = common_window(base, [c.fit_patches for c in d.cells])
    assert win == (775.0, 788.0)
    xy = _spectrum(noise=10.0)
    recs = [
        fit_cell(xy, base, list(c.fit_patches), spectrum_id="s", cell_id=c.cell_id, responses=RESPONSES, window=win)
        for c in d.cells
    ]
    assert all(r["error"] is None for r in recs)
    # wide and narrow windows fit different numbers of points, but the common-window count is identical
    assert len({r["n_points"] for r in recs}) == 2
    assert len({r["n_common"] for r in recs}) == 1
    assert all(r["bic_common"] is not None for r in recs)


def test_multistart_flags_a_degenerate_cell():
    # two coincident peaks: area can move freely between them at equal cost
    x = np.linspace(790.0, 772.0, 301)
    y = 500.0 + _gl(x, 781.0, 3000.0, 1.6) + np.random.default_rng(1).normal(0, 15.0, x.shape)
    params = {
        "technique_family": "xps",
        "components": [
            {"component_id": "bg", "component_type": "linear_bg"},
            {"component_id": "A", "component_type": "gaussian"},
            {"component_id": "B", "component_type": "gaussian"},
        ],
        "p0": [500.0, 500.0, 781.0, 1500.0, 1.6, 781.0, 1500.0, 1.6],
        "bounds_lower": [None, None, 780.0, 0.0, 0.5, 780.0, 0.0, 0.5],
        "bounds_upper": [None, None, 782.0, None, 3.0, 782.0, None, 3.0],
        "vary": [False, False, True, True, True, True, True, True],
    }
    rec = fit_cell(XY(x=x, y=y), params, [], spectrum_id="s", cell_id="c", responses=RESPONSES[:1], n_starts=8, seed=3)
    assert rec["error"] is None
    assert rec["n_equivalent_starts"] >= 1
    assert rec["degenerate"] and "B_pct" in rec["degenerate_responses"]


# ------------------------------------------------------------------ study


def _run_study(n_spectra=4):
    d = build_design(FACTORS)
    base = _base_params()
    win = common_window(base, [c.fit_patches for c in d.cells])
    recs, x_by = [], {}
    for i in range(n_spectra):
        sid = f"s{i}"
        x_by[sid] = float(i)
        xy = _spectrum(seed=i, frac2=0.2 + 0.1 * i, noise=15.0)
        for c in d.cells:
            recs.append(fit_cell(xy, base, list(c.fit_patches), spectrum_id=sid, cell_id=c.cell_id, responses=RESPONSES, window=win))
    return d, recs, x_by


def test_summarize_study_end_to_end():
    d, recs, x_by = _run_study()
    out = summarize_study(d, recs, RESPONSES, x_by_spectrum=x_by, filter_spec={"mode": "delta_bic_common", "threshold": 1e6})
    r = out["responses"]["B_frac"]
    assert r["anova"]["n_spectra"] == 4
    terms = {t["term"]: t for t in r["anova"]["terms"]}
    assert set(["background", "window", "fwhm"]) <= set(terms)
    tr = r["trend"]
    assert tr["reference_sign"] == 1.0
    assert tr["fraction_sign_preserved"] == pytest.approx(1.0)
    assert len(tr["bands"]) == 4
    # filter report lists every level of every factor
    assert set(out["filter"]["by_level"]["background"]) == {"shirley", "linear"}
    assert out["filter"]["n_kept"] + out["filter"]["n_removed"] == out["filter"]["n_total"] - out["filter"]["n_failed"]


def test_filter_modes_and_noise_comparison():
    d, recs, x_by = _run_study(n_spectra=2)
    kept_none, _ = apply_filter(recs, d, None)
    kept_tight, rep = apply_filter(recs, d, {"mode": "delta_bic_common", "threshold": 0.0})
    assert len(kept_tight) < len(kept_none)
    with pytest.raises(ValueError):
        apply_filter(recs, d, {"mode": "bogus"})
    noise = {"B_frac": {"s0": [0.30, 0.31, 0.29, 0.30], "s1": [0.40, 0.41, 0.39, 0.40]}}
    out = summarize_study(d, recs, RESPONSES, x_by_spectrum=x_by, noise=noise)
    nc = out["responses"]["B_frac"]["noise_comparison"]
    assert nc["n_spectra"] == 2 and nc["ratio_var_median"] is not None and math.isfinite(nc["ratio_var_median"])


# ------------------------------------------------------------------ constraints (exclusion rules)


WIDTH_FACTORS = [
    {"name": "fwhm_co3", "levels": [
        {"name": "2.6", "values": {"w3": 2.6}}, {"name": "1.8", "values": {"w3": 1.8}},
        {"name": "2.2", "values": {"w3": 2.2}}, {"name": "3.0", "values": {"w3": 3.0}},
    ]},
    {"name": "relation", "levels": [
        {"name": "current", "values": {"rel": 1.0, "extra": 0.4}},
        {"name": "1:1:1", "values": {"rel": 1.0, "extra": 0.0}},
        {"name": "1:1.1:1.1", "values": {"rel": 1.1, "extra": 0.0}},
        {"name": "1:1.2:1.2", "values": {"rel": 1.2, "extra": 0.0}},
    ]},
]


def test_constraint_exclude_when_drops_matching_cells_only():
    d = build_design(FACTORS, constraints=[{"name": "no narrow linear", "exclude_when": {"background": ["linear"], "window": ["narrow"]}}])
    assert len(d.cells) == 6 and d.n_full == 8 and d.n_excluded == 2
    assert d.excluded_by == {"no narrow linear": 2}
    assert not d.exact and any("unbalanced" in n for n in d.notes)
    assert ("linear", "narrow", "free") not in {c.levels for c in d.cells}
    assert d.cells[0].levels == tuple(f["levels"][0]["name"] for f in FACTORS)  # nominal stays first
    pub = d.to_public_dict()
    assert pub["n_excluded"] == 2 and pub["excluded_by_rule"] == {"no narrow linear": 2}


def test_constraint_that_removes_nothing_keeps_design_exact():
    d = build_design(FACTORS, constraints=[{"require": "1 <= 2"}])
    assert len(d.cells) == 8 and d.exact and d.n_excluded == 0


def test_constraint_require_expression_on_level_values():
    # Co2+ width = w3 * rel + extra must stay <= 3.2 eV and the Co3+ width >= 1.8 eV
    rule = [{"name": "co2 width", "require": "w3 * rel + extra <= 3.2 and w3 >= 1.8"}]
    d = build_design(WIDTH_FACTORS, constraints=rule)
    kept = {c.levels for c in d.cells}
    assert ("3.0", "1:1:1") in kept  # 3.0 * 1.0 = 3.0, within the 1e-9 tolerance logic
    assert ("3.0", "current") not in kept  # 3.4
    assert ("3.0", "1:1.2:1.2") not in kept  # 3.6
    assert ("2.6", "1:1.2:1.2") in kept  # 3.12
    assert ("1.8", "current") in kept
    assert len(d.cells) + d.n_excluded == 16 == d.n_full
    # exact boundary: 2.0 * 1.6 = 3.2 is kept (tolerance), 2.0 * 1.6 + 0.01 is not
    edge = build_design(
        [{"name": "a", "levels": [{"name": "n", "values": {"x": 2.0}}, {"name": "m", "values": {"x": 2.0}}]},
         {"name": "b", "levels": [{"name": "p", "values": {"y": 1.6}}, {"name": "q", "values": {"y": 1.61}}]}],
        constraints=[{"require": "x * y <= 3.2"}],
    )
    assert {c.levels for c in edge.cells} == {("n", "p"), ("m", "p")}


def test_constraint_cap_counts_cells_after_exclusion_and_subsample_draws_from_pool():
    rule = [{"require": "w3 * rel + extra <= 3.2 and w3 >= 1.8"}]
    n_kept = len(build_design(WIDTH_FACTORS, constraints=rule).cells)
    assert len(build_design(WIDTH_FACTORS, constraints=rule, max_cells=n_kept).cells) == n_kept
    with pytest.raises(DesignError, match="max_cells"):
        build_design(WIDTH_FACTORS, constraints=rule, max_cells=n_kept - 1)
    allowed = {c.level_index for c in build_design(WIDTH_FACTORS, constraints=rule).cells}
    sub = build_design(WIDTH_FACTORS, constraints=rule, subsample={"n": 5, "seed": 3})
    assert len(sub.cells) == 5 and {c.level_index for c in sub.cells} <= allowed
    sub2 = build_design(WIDTH_FACTORS, constraints=rule, subsample={"n": 5, "seed": 3})
    assert [c.level_index for c in sub.cells] == [c.level_index for c in sub2.cells]


def test_constraint_hash_depends_on_rules_and_is_stable():
    r1 = [{"exclude_when": {"background": ["linear"], "window": ["narrow"]}}]
    r2 = [{"exclude_when": {"background": ["linear"], "fwhm": ["tied"]}}]
    h1 = build_design(FACTORS, constraints=r1).design_hash()
    assert h1 == build_design(FACTORS, constraints=r1).design_hash()
    assert h1 != build_design(FACTORS, constraints=r2).design_hash()
    assert h1 != build_design(FACTORS).design_hash()


@pytest.mark.parametrize(
    "rules, match",
    [
        ([{"exclude_when": {"nope": ["a"]}}], "unknown factor"),
        ([{"exclude_when": {"background": ["zzz"]}}], "no level"),
        ([{"exclude_when": {"background": ["linear"]}, "require": "1 < 2"}], "exactly one"),
        ([{"name": "x"}], "exactly one"),
        ([{"require": "__import__('os').system('x')"}], "only abs / min / max|not allowed"),
        ([{"require": "w3.real > 1"}], "not allowed"),
        ([{"require": "undefined_name > 1"}], "unknown name"),
        ([{"require": "1 <"}], "not valid"),
        ([{"require": "'a' == 'a'"}], "only numbers"),
        ([{"name": "d", "require": "1 < 2"}, {"name": "d", "require": "1 < 3"}], "duplicate constraint"),
        ("not a list", "list of rules"),
    ],
)
def test_constraint_rejects_bad_rules(rules, match):
    with pytest.raises(DesignError, match=match):
        build_design(FACTORS, constraints=rules)


def test_constraint_cannot_remove_the_nominal_cell_or_leave_nothing():
    with pytest.raises(DesignError, match="nominal"):
        build_design(FACTORS, constraints=[{"exclude_when": {"background": ["shirley"]}}])
    with pytest.raises(DesignError, match="nominal|fewer than 2"):
        build_design(FACTORS, constraints=[{"require": "1 > 2"}])


def test_level_values_are_validated():
    with pytest.raises(DesignError, match="every level"):
        build_design([{"name": "a", "levels": [{"name": "x", "values": {"v": 1}}, {"name": "y"}]}, FACTORS[1]])
    with pytest.raises(DesignError, match="used by factors"):
        build_design([
            {"name": "a", "levels": [{"name": "x", "values": {"v": 1}}, {"name": "y", "values": {"v": 2}}]},
            {"name": "b", "levels": [{"name": "x", "values": {"v": 1}}, {"name": "y", "values": {"v": 2}}]},
        ])
    with pytest.raises(DesignError, match="finite number"):
        build_design([{"name": "a", "levels": [{"name": "x", "values": {"v": "high"}}, {"name": "y", "values": {"v": 2}}]}])
    with pytest.raises(DesignError, match="usable value name"):
        build_design([{"name": "a", "levels": [{"name": "x", "values": {"min": 1}}, {"name": "y", "values": {"min": 2}}]}])


def test_constrained_study_runs_end_to_end_with_sequential_anova():
    d = build_design(FACTORS, constraints=[{"exclude_when": {"background": ["linear"], "window": ["narrow"]}}])
    base = _base_params()
    win = common_window(base, [c.fit_patches for c in d.cells])
    recs = []
    for i in range(2):
        xy = _spectrum(seed=i, frac2=0.2 + 0.1 * i, noise=15.0)
        for c in d.cells:
            recs.append(fit_cell(xy, base, list(c.fit_patches), spectrum_id=f"s{i}", cell_id=c.cell_id, responses=RESPONSES, window=win))
    out = summarize_study(d, recs, RESPONSES)
    anova_block = out["responses"]["B_frac"]["anova"]
    assert anova_block["n_spectra"] == 2
    assert out["design"]["n_excluded"] == 2 and not out["design"]["exact"]
    assert {t["term"] for t in anova_block["terms"]} >= {"background", "window", "fwhm"}
    assert anova_block["exact"] is False and anova_block["n_spectra_exact"] == 0
