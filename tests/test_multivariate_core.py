from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.multivariate import (
    correlation_matrix,
    preprocess_matrix,
    rotate_pca_result,
    run_mcr_als,
    run_nmf,
    twod_cos,
)


def _synthetic(n: int = 40, p: int = 120, seed: int = 0):
    rng = np.random.default_rng(seed)
    x = np.linspace(100, 1000, p)
    s1 = np.exp(-0.5 * ((x - 300) / 20) ** 2)
    s2 = np.exp(-0.5 * ((x - 700) / 25) ** 2)
    c1 = np.linspace(1, 0, n)
    c = np.stack([c1, 1 - c1], axis=1)
    S = np.stack([s1, s2])
    Y = c @ S + 0.002 * rng.standard_normal((n, p))
    return Y, x, c, S, [f"s{i}" for i in range(n)]


def test_preprocess_steps_and_shapes():
    Y, x, *_ = _synthetic()
    Yp, xp, meta = preprocess_matrix(
        Y, x, {"crop": [200, 900], "bin": 2, "smooth_window": 5, "row_norm": "snv", "scale": "pareto"}
    )
    assert Yp.shape[0] == Y.shape[0] and Yp.shape[1] == xp.size < Y.shape[1]
    assert xp.min() >= 195 and xp.max() <= 905
    assert any("savgol" in s for s in meta["steps"])
    assert np.allclose(Yp.mean(axis=0), 0, atol=1e-9)  # mean-centred by default


def test_preprocess_nonneg_disables_centering():
    Y, x, *_ = _synthetic()
    Yp, _, meta = preprocess_matrix(Y - 0.01, x, {"center": "mean"}, require_nonneg=True)
    assert Yp.min() >= 0
    assert any("centring disabled" in w for w in meta["warnings"])


def test_preprocess_bad_option():
    Y, x, *_ = _synthetic()
    with pytest.raises(ValueError):
        preprocess_matrix(Y, x, {"row_norm": "bogus"})


def test_correlation_and_reorder():
    Y, x, _, _, sids = _synthetic()
    r = correlation_matrix(Y, x, sids, axis="channels", method="spearman", reorder=True)
    R = np.asarray(r["R"])
    assert R.shape == (x.size, x.size) and r["reordered"]
    assert sorted(r["order"]) == list(range(x.size))
    assert np.allclose(np.diag(R), 1.0)
    rs = correlation_matrix(Y, x, sids, axis="samples")
    assert np.asarray(rs["R"]).shape == (len(sids), len(sids))


def test_nmf_recovers_two_components():
    Y, x, c, S, sids = _synthetic()
    Y = np.clip(Y, 0, None)
    r = run_nmf(Y, x, sids, n_components=2, n_starts=3, scan_k=[1, 2, 3])
    assert r["r2"] > 0.99
    assert [d["k"] for d in r["scan"]] == [1, 2, 3]
    H = np.asarray(r["components"])
    # each recovered spectrum correlates strongly with one true spectrum
    cc = np.abs(np.corrcoef(np.vstack([H, S]))[:2, 2:])
    assert (cc.max(axis=1) > 0.98).all()


def test_mcr_als_constraints_and_fixed():
    Y, x, c, S, sids = _synthetic()
    Y = np.clip(Y, 0, None)
    r = run_mcr_als(Y, x, sids, n_components=2, closure=True)
    C = np.asarray(r["scores"])
    assert (C >= -1e-9).all() and r["r2"] > 0.98
    r2 = run_mcr_als(Y, x, sids, n_components=2, fixed_spectrum_ids=["s0"], unimodal_spec=True)
    assert r2["fixed_spectrum_ids"] == ["s0"]
    with pytest.raises(ValueError):
        run_mcr_als(Y - 1.0, x, sids, n_components=2)


def test_varimax_preserves_reconstruction():
    from sklearn.decomposition import PCA

    Y, x, *_ = _synthetic()
    Yc = Y - Y.mean(axis=0)
    pca = PCA(n_components=3)
    T = pca.fit_transform(Yc)
    res = {
        "components": pca.components_.tolist(),
        "scores": T.tolist(),
        "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
    }
    rot = rotate_pca_result(res)
    rec0 = np.asarray(res["scores"]) @ np.asarray(res["components"])
    rec1 = np.asarray(rot["scores"]) @ np.asarray(rot["components"])
    assert np.allclose(rec0, rec1, atol=1e-8)
    assert sum(rot["explained_variance_ratio"]) == pytest.approx(sum(res["explained_variance_ratio"]), rel=1e-6)


def test_twod_cos_sync_symmetric_async_antisymmetric():
    Y, x, *_ = _synthetic(n=30, p=60)
    r = twod_cos(Y, x, np.arange(30.0))
    sync, asyn = np.asarray(r["synchronous"]), np.asarray(r["asynchronous"])
    assert np.allclose(sync, sync.T)
    assert np.allclose(asyn, -asyn.T, atol=1e-8)
    # uneven perturbation is resampled
    t = np.sort(np.random.default_rng(1).uniform(0, 10, 30))
    assert twod_cos(Y, x, t)["resampled"]
    with pytest.raises(ValueError):
        twod_cos(Y, x, np.ones(30))
