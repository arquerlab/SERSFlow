"""Depth alignment + contiguous segmentation (core/multivariate/depth.py, explore_stats wrappers)."""

from __future__ import annotations

import os

import numpy as np
import pytest

from sersflow.api.services.explore_stats import (
    _jsonable,
    compute_depth_alignment,
    compute_segments,
)
from sersflow.core.multivariate import depth as dp


def _grid(seed: int = 0):
    """3x3 map positions x 40 z steps. Sustanion-like step at z=50+tilt; 3 zones in the other features."""
    rng = np.random.default_rng(seed)
    z0 = np.arange(0.0, 200.0, 5.0)
    rows = []
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            tilt = 5.0 * x - 10.0 * y  # true edge shift of this position (multiple of the z step)
            for z in z0:
                edge = 100.0 + tilt
                prof = 10.0 if z < edge else 1.0
                zone = np.digitize(z - tilt, [60.0, 140.0])  # zones follow the tilted interface
                f1 = [5.0, 1.0, 3.0][zone]
                f2 = [0.0, 4.0, 0.5][zone]
                rows.append((x, y, z, prof + rng.normal(0, 0.1), f1 + rng.normal(0, 0.1), f2 + rng.normal(0, 0.1)))
    a = np.array(rows)
    return a[:, 2], a[:, :2], a[:, 3], a[:, 4:6]


def test_edge_on_clean_step():
    z = np.arange(0.0, 100.0, 5.0)
    y = np.where(z < 42.5, 10.0, 2.0)
    e = dp.interface_edge_z(z, y, smooth=1)
    assert 40.0 <= e <= 45.0
    assert np.isnan(dp.interface_edge_z(z, np.ones_like(z)))  # no step


def test_edge_direction_up():
    z = np.arange(0.0, 100.0, 5.0)
    y = np.where(z < 50, 1.0, 9.0)
    assert 45 <= dp.interface_edge_z(z, y, smooth=1, direction="up") <= 55


def test_shifts_reference_fixed_and_recovered():
    z, pos, prof, _ = _grid()
    res = compute_depth_alignment(z, pos, prof, {"smooth": 1, "reference": [0, 0]})
    assert res["reference"] == [0.0, 0.0]
    tab = {tuple(t["position"]): t["shift"] for t in res["positions"]}
    assert tab[(0.0, 0.0)] == pytest.approx(0.0)
    # true shifts are 5x - 10y (multiples of the z step)
    for (x, y), s in tab.items():
        assert abs(s - (5 * x - 10 * y)) <= 1.0
    # aligned z collapses the positions onto one interface
    z_al = res["z_aligned"]
    centre = (pos == [0, 0]).all(1)
    assert np.allclose(z_al[centre], z[centre])


def test_default_reference_is_centre():
    r = dp.position_z_shifts({(0.0, 0.0): 10.0, (1.0, 0.0): 12.0, (-1.0, 0.0): 8.0, (0.0, 1.0): 10.0, (0.0, -1.0): 10.0})
    assert r["reference"] == (0.0, 0.0)
    assert r["shifts"][(1.0, 0.0)] == pytest.approx(2.0)


def test_contiguous_matches_brute_force():
    rng = np.random.default_rng(1)
    F = np.vstack([rng.normal(0, 0.1, (6, 2)), rng.normal(3, 0.1, (5, 2)), rng.normal(-2, 0.1, (7, 2))])
    w = rng.uniform(1, 3, len(F))
    sol = dp.contiguous_segments(F, w, 3)
    # brute force K=3
    best = (np.inf, None)
    n = len(F)

    def cost(i, j):
        ww, f = w[i:j], F[i:j]
        m = (ww[:, None] * f).sum(0) / ww.sum()
        return float((ww[:, None] * (f - m) ** 2).sum())

    for a in range(1, n - 1):
        for b in range(a + 1, n):
            c = cost(0, a) + cost(a, b) + cost(b, n)
            if c < best[0]:
                best = (c, [a, b])
    assert sol[3][0] == pytest.approx(best[0])
    assert sol[3][1] == best[1] == [6, 11]
    costs = [sol[k][0] for k in (1, 2, 3)]
    assert costs[0] > costs[1] > costs[2]


def test_segments_with_alignment_recovers_zones():
    z, pos, prof, F = _grid()
    al = compute_depth_alignment(z, pos, prof, {"smooth": 1, "reference": [0, 0]})
    res = compute_segments(
        al["z_aligned"], F, method="contiguous", n_segments=3, k_max=4, bin_width=5.0, pos=pos, names=["a", "b"]
    )
    cuts = res["cuts"]
    assert len(cuts) == 2
    assert abs(cuts[0] - 60.0) <= 8 and abs(cuts[1] - 140.0) <= 8
    lab = res["labels_array"]
    assert (np.diff(lab[np.argsort(al["z_aligned"], kind="stable")]) >= 0).all()  # contiguous in z
    assert res["cost_by_k"][3] < res["cost_by_k"][2] < res["cost_by_k"][1]
    assert len(res["per_position_cuts"]) == 9
    assert [s["n"] for s in res["segments"]] == [int((lab == c).sum()) for c in range(3)]


def test_kmeans_numbered_by_z_and_reports_contiguity():
    z, pos, prof, F = _grid()
    res = compute_segments(z, F, method="kmeans", n_segments=3, k_max=4, n_init=20)
    med = [s["z_median"] for s in res["segments"]]
    assert med == sorted(med)
    assert set(res["silhouette_by_k"]) == {2, 3, 4}
    assert 0.0 <= res["contiguity"] <= 1.0


def test_prepare_features_tames_outlier_and_keeps_nan():
    X = np.column_stack([np.r_[np.ones(99), 500.0], np.arange(100.0)])
    X[3, 1] = np.nan
    F = dp.prepare_features(X)
    assert np.isnan(F[3, 1])
    assert np.nanmax(np.abs(F)) < 10
    assert abs(np.nanmean(F[:, 1])) < 1e-9


def test_jsonable_strict():
    out = _jsonable({1: np.float64("nan"), "a": np.arange(2), "b": (np.int64(3), float("inf"))})
    assert out == {"1": None, "a": [0, 1], "b": [3, None]}


_REAL = os.path.join(
    os.path.dirname(__file__), "..", ".sersflow_mcp_exports", "analysis_arun_22399f02591345109ece8092d77be1fb_observation.csv"
)


@pytest.mark.skipif(not os.path.exists(_REAL), reason="PH_volume_test observation export not available")
def test_real_ph_volume_reference_numbers():
    pd = pytest.importorskip("pandas")
    d = pd.read_csv(_REAL)
    pos = d[["axis_map_x", "axis_map_y"]].values
    p = {
        "plateau_z_max": -40.0,
        "low_z_range": [-30.0, 60.0],
        "search_z_min": -60.0,
        "reference": [0, 0],
    }
    al = compute_depth_alignment(d.axis_z.values, pos, d["s7_fit_Sustanion_amp"].values, p)
    assert al["reference_edge_z"] == pytest.approx(-21.295, abs=1e-3)
    assert al["shift_min"] == pytest.approx(-5.246, abs=1e-3)
    assert al["shift_max"] == pytest.approx(8.394, abs=1e-3)
    comps = [("s7", n) for n in ("Sustanion", "1030", "bicarbonate", "carbonate", "1131", "1182", "1200")] + [
        ("s10", n) for n in ("CO_rot", "CO_str", "Cinter_OH", "OH_713", "O_600")
    ]
    A = np.column_stack([d[f"{s}_fit_{n}_area"] for s, n in comps])
    res = compute_segments(al["z_aligned"], A, method="contiguous", n_segments=4, k_max=4, per_position_check=False)
    assert res["cuts"] == [-62.5, -27.5, 82.5]
    assert np.bincount(res["labels_array"]).tolist() == [390, 343, 1078, 1129]
    km = compute_segments(al["z_aligned"], A, method="kmeans", n_segments=4, k_max=4)
    assert sorted(s["n"] for s in km["segments"]) == [218, 661, 866, 1195]


def test_depth_routes_roundtrip(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from sersflow.api.routers import explore as ex
    from sersflow.api.schemas.explore import DepthAlignRequest, SegmentsRequest
    from sersflow.mcp import summarize

    z, pos, prof, F = _grid()
    cols = {"axis_z": z, "axis_map_x": pos[:, 0], "axis_map_y": pos[:, 1], "fit_amp": prof, "fit_a": F[:, 0], "fit_b": F[:, 1]}

    def loader(_run, names):
        return np.column_stack([cols[n] for n in names]), [f"sp{i}" for i in range(len(z))], names

    import sersflow.api.services.explore_stats as st

    monkeypatch.setattr(st, "load_explore_feature_matrix", loader)
    monkeypatch.setattr(ex, "get_run_for_user", lambda *_a, **_k: SimpleNamespace(status="completed", dataset_id="ds"))
    monkeypatch.setattr(ex, "current_user_id", lambda *_a, **_k: "dev")
    monkeypatch.setattr(ex, "_artifact_subdir", lambda sub: str(tmp_path / sub))
    monkeypatch.setattr(ex, "create_explore_run", lambda **_k: "eid1")
    monkeypatch.setattr(ex, "finish_explore_run", lambda **_k: None)
    monkeypatch.setattr(ex, "prune_explore_runs", lambda **_k: None)

    out = ex.post_depth_align(
        DepthAlignRequest(analysis_run_id="r", feature_column="fit_amp", smooth=1, reference=[0, 0]), object()
    )
    assert out.results["n_positions"] == 9 and len(out.results["z_aligned"]) == len(z)

    req = SegmentsRequest(
        analysis_run_id="r",
        feature_columns=["fit_a", "fit_b"],
        n_segments=3,
        k_max=4,
        zone_names=["bottom", "mid"],
        align={"feature_column": "fit_amp", "smooth": 1, "reference": [0, 0]},
    )
    out = ex.post_segments(req, object())
    r = out.results
    assert len(r["cuts"]) == 2 and r["zone_names"] == ["bottom", "mid", "Segment 3"]
    assert r["alignment"]["reference"] == [0.0, 0.0] and len(r["labels"]) == len(r["spectrum_ids"])
    s = summarize.depth_result(out)
    assert s["cuts"] == r["cuts"] and "labels" not in s and s["per_position_cut_mean"]

    km = ex.post_segments(req.model_copy(update={"method": "kmeans", "align": None}), object())
    assert km.results["method"] == "kmeans" and "silhouette_by_k" in km.results
