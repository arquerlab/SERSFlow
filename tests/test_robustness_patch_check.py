"""Patch-effect check (Feature A): inert / insensitive distinction, hashes, prepare/solve equivalence."""
from __future__ import annotations

import os
import subprocess
import sys
import time

import numpy as np

os.environ.setdefault("SERSFLOW_ENV", "test")

from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params  # noqa: E402
from sersflow.core.robustness.cell_fit import fit_cell, prepare_fit, solve_fit  # noqa: E402
from sersflow.core.robustness.design import build_design  # noqa: E402
from sersflow.core.robustness.fit_hash import data_hash_of  # noqa: E402
from sersflow.core.robustness.patch_check import (  # noqa: E402
    DUPLICATE_PREFIX,
    INERT,
    OK,
    START_ONLY,
    UNRESOLVED,
    UPSTREAM_INERT,
    run_patch_check,
)
from sersflow.core.spectrum import XY  # noqa: E402


def _xy(seed: int = 0, n: int = 240) -> XY:
    rng = np.random.default_rng(seed)
    x = np.linspace(0.0, 12.0, n)
    y = 5.0 + 0.1 * x + 40 * np.exp(-4 * np.log(2) * ((x - 4) / 1.2) ** 2) + 25 * np.exp(
        -4 * np.log(2) * ((x - 8) / 1.5) ** 2
    )
    return XY(x, y + rng.normal(0, 0.3, n))


def _params() -> dict:
    return {
        "technique_family": "vibrational",
        "components": [
            {"component_id": "bg", "component_type": "polynomial_background", "degree": 1},
            {"component_id": "a", "component_type": "gaussian"},
            {"component_id": "b", "component_type": "gaussian"},
        ],
        "p0": [0.1, 5.0, 4.1, 30.0, 1.3, 7.9, 20.0, 1.6],
        "bounds_lower": [None, None, None, 0.0, 0.1, None, 0.0, 0.1],
        "bounds_upper": [None, None, None, None, None, None, None, None],
        "vary": [True] * 8,
        "fit_min_x": None,
        "fit_max_x": None,
    }


STEPS = [
    {"index": 0, "id": "s0", "name": "baseline", "enabled": True, "params": {"method": "als", "lam": 1e5}},
    {"index": 1, "id": "s1", "name": "fitting", "enabled": True, "params": _params()},
]


def _prefit(_patches):
    return {"sp1": _xy(1), "sp2": _xy(2)}


def _check(factors, prefit=_prefit):
    d = build_design(factors)
    return {(r.factor, r.level): r for r in run_patch_check(d, _params(), STEPS, 1, prefit).rows}


def _lv(name, *patches):
    return {"name": name, "patches": list(patches)}


def _setp(cid, key, **kw):
    return {"op": "set_component_param", "select": {"component_ids": [cid]}, "key": key, **kw}


def test_misspelled_key_is_unresolved():
    rows = _check([{"name": "f", "levels": [_lv("nom"), _lv("bad", _setp("a", "posx", value=3.0))]}])
    r = rows[("f", "bad")]
    assert r.status == UNRESOLVED
    assert any("posx" in n for n in r.notes)


def test_misspelled_step_key_is_unresolved():
    patch = {"op": "set_step_param", "key": "fit_min_xx", "value": 1.0}
    rows = _check([{"name": "f", "levels": [_lv("nom"), _lv("bad", patch)]}])
    assert rows[("f", "bad")].status == UNRESOLVED


def test_set_on_tied_param_is_inert():
    tie = {"op": "tie_param", "select": {"component_ids": ["a", "b"]}, "key": "pos", "mode": "equal"}
    rows = _check(
        [
            {"name": "tie", "levels": [_lv("tied", tie), _lv("also_tied", tie)]},
            {"name": "bpos", "levels": [_lv("nom"), _lv("moved", _setp("b", "pos", value=5.0))]},
        ]
    )
    assert rows[("bpos", "moved")].status == INERT


def test_upstream_key_that_the_step_ignores_is_upstream_inert():
    patch = {"op": "set_step_param", "target": {"step_name": "baseline"}, "key": "lam", "value": 1e7}
    rows = _check([{"name": "base", "levels": [_lv("nom"), _lv("heavy", patch)]}], prefit=_prefit)  # prefit ignores it
    assert rows[("base", "heavy")].status == UPSTREAM_INERT


def test_upstream_key_that_changes_the_data_is_ok():
    patch = {"op": "set_step_param", "target": {"step_name": "baseline"}, "key": "lam", "value": 1e7}

    def prefit(patches):
        scale = 1.5 if patches else 1.0
        return {k: XY(v.x, v.y * scale) for k, v in _prefit(patches).items()}

    rows = _check([{"name": "base", "levels": [_lv("nom"), _lv("heavy", patch)]}], prefit=prefit)
    assert rows[("base", "heavy")].status == OK


def test_identical_levels_are_duplicates():
    p = _setp("a", "fwhm", value=2.0, vary=False)
    rows = _check([{"name": "f", "levels": [_lv("nom"), _lv("one", p), _lv("two", p)]}])
    assert rows[("f", "one")].status == OK
    assert rows[("f", "two")].status == DUPLICATE_PREFIX + "one"


def test_init_only_change_is_start_only():
    rows = _check([{"name": "f", "levels": [_lv("nom"), _lv("init", _setp("a", "pos", value=4.3))]}])
    assert rows[("f", "init")].status == START_ONLY


def test_position_change_with_bounds_or_fixed_is_ok():
    rows = _check(
        [
            {
                "name": "f",
                "levels": [
                    _lv("nom"),
                    _lv("fixed", _setp("a", "pos", value=4.3, vary=False)),
                    _lv("bounded", _setp("a", "pos", value=4.3, lower=4.0, upper=4.6)),
                ],
            }
        ]
    )
    assert rows[("f", "fixed")].status == OK
    assert rows[("f", "bounded")].status == OK


def test_fit_window_change_is_ok_and_changes_n_points():
    win = {"op": "set_step_param", "key": "fit_min_x", "value": 2.0}
    rows = _check([{"name": "win", "levels": [_lv("nom"), _lv("narrow", win)]}])
    assert rows[("win", "narrow")].status == OK
    a = fit_cell(_xy(1), _params(), [], spectrum_id="sp1", cell_id="c0", responses=[])
    b = fit_cell(_xy(1), _params(), [win], spectrum_id="sp1", cell_id="c1", responses=[])
    assert a["error"] is None and b["error"] is None
    assert b["n_points_fit"] < a["n_points_fit"]
    assert b["fit_x_min"] >= 2.0 - 1e-9


def test_solve_of_prepare_matches_the_direct_path_bit_for_bit():
    xy = _xy(3)
    patches = [_setp("a", "fwhm", value=1.4, lower=0.5, upper=3.0)]
    rec = fit_cell(xy, _params(), patches, spectrum_id="s", cell_id="c", responses=[], n_starts=1)
    from sersflow.core.robustness.patches import apply_fit_patches

    prob = fit_problem_from_step_params(xy, apply_fit_patches(_params(), patches))
    res = fit_curve(prob)
    assert rec["p_opt"] == [float(v) for v in np.asarray(res.p_opt, dtype=float)]
    assert rec["chi2"] == float(res.diagnostics.chi2)
    prep = prepare_fit(xy, _params(), patches)
    out = solve_fit(prep, spectrum_id="s", cell_id="c", responses=[])
    assert out["p_opt"] == rec["p_opt"]


def test_record_carries_the_hash_fields():
    rec = fit_cell(_xy(1), _params(), [], spectrum_id="s", cell_id="c", responses=[], prefit_data_hash="abc")
    for k in ("fit_config_hash", "fit_start_hash", "n_points_fit", "fit_x_min", "fit_x_max", "patch_check_version", "prefit_data_hash"):
        assert k in rec, k


def test_hashes_are_stable_across_processes():
    code = (
        "import os; os.environ['SERSFLOW_ENV']='test'\n"
        "import numpy as np\n"
        "from sersflow.core.robustness.fit_hash import data_hash_of, sha256_hex\n"
        "x=np.linspace(0,1,50); y=np.sin(x)\n"
        "print(data_hash_of(x,y), sha256_hex({'b':[1.0000000000001,2],'a':0.1+0.2}))\n"
    )
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout for _ in range(2)}
    assert len(outs) == 1
    x = np.linspace(0, 1, 50)
    assert data_hash_of(x, 2 + np.sin(x)) == data_hash_of(x.copy(), 2 + np.sin(x) + 1e-15)  # below 12 significant digits


def test_check_is_fast_for_a_realistic_design():
    factors = []
    for i in range(9):
        lv = [_lv("L0")] + [_lv(f"L{k}", _setp("a", "fwhm", value=1.0 + 0.1 * i + 0.05 * k, vary=False)) for k in range(1, 5)]
        factors.append({"name": f"f{i}", "levels": lv})
    d = build_design(factors, max_cells=None, subsample={"n": 400, "seed": 0})
    prefit = lambda _p: {f"sp{k}": _xy(k) for k in range(8)}  # noqa: E731
    t0 = time.perf_counter()
    rep = run_patch_check(d, _params(), STEPS, 1, prefit)
    assert time.perf_counter() - t0 < 30
    assert len(rep.rows) == 9 * 4
