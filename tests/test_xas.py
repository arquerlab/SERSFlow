from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy.special import erf

from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.services.datasets_service import _dataset_family
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.technique import (
    assert_matching_technique_families,
    block_technique_family,
    normalize_technique_family,
    sniff_technique_from_axis_label,
)
from sersflow.core.pipeline.library.registry import list_steps
from sersflow.core.pipeline.steps import DEFAULT_STEPS
from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_curve
from sersflow.core.preprocess.xas import normalize_edge_step
from sersflow.core.spectrum import XY
from test_sle_loader import _write_sle


def _edge(x: np.ndarray, *, e0: float = 530.0, pre: float = 2.0, step: float = 5.0, slope: float = 0.0):
    """erf edge (light tails) on a sloping background; the post-edge level is pre + step at E0."""
    return (
        pre
        + 0.01 * (x - e0)
        + step * 0.5 * (1.0 + erf((x - e0) / 1.0))
        + slope * np.clip(x - e0, 0, None)
    )


def test_xas_is_a_known_technique_family() -> None:
    assert normalize_technique_family("XAS") == "xas"
    assert sniff_technique_from_axis_label("Photon energy (eV)") == "xas"
    assert sniff_technique_from_axis_label("Binding energy") == "xps"
    assert sniff_technique_from_axis_label("Raman shift") == "vibrational"
    assert assert_matching_technique_families("xas", "xas") == "xas"
    with pytest.raises(ValueError, match="technique_family mismatch"):
        assert_matching_technique_families("xas", "xps")
    with pytest.raises(ValueError, match="Invalid technique_family"):
        normalize_technique_family("nmr")
    assert Pipeline(steps=[], technique_family="xas").technique_family == "xas"
    assert DatasetMetadata(technique_family="xas").technique_family == "xas"


def test_block_technique_family_reads_meta() -> None:
    assert block_technique_family({"technique": "XAS"}) == "xas"
    assert block_technique_family({"technique": "NEXAFS"}) == "xas"
    assert block_technique_family({"technique": "XPS"}) == "xps"
    assert block_technique_family({"technique": "Raman"}) is None
    assert block_technique_family(None) is None


def test_xas_normalize_step_only_offered_for_xas() -> None:
    ids = {fam: {s.id for s in list_steps(technique_family=fam)} for fam in ("vibrational", "xps", "xas")}
    assert "xas_normalize" in ids["xas"]
    assert "xas_normalize" not in ids["xps"] and "xas_normalize" not in ids["vibrational"]
    assert "baseline" in ids["xas"] and "noise_savgol" in ids["xas"]  # generic steps still apply


def test_edge_step_normalization_unit_pre_and_post_edge() -> None:
    x = np.linspace(510.0, 560.0, 1001)
    y = _edge(x)
    res = normalize_edge_step(x, y, e0=530.0, pre_degree=1, post_degree=1)
    assert res.e0 == 530.0
    # Pre-edge region sits at 0, post-edge region near 1 (arctan tails + background slope are small).
    assert abs(res.y[x < 520].mean()) < 0.02
    assert abs(res.y[x > 550].mean() - 1.0) < 0.08
    assert res.edge_step == pytest.approx(5.0, rel=0.02)


def test_edge_step_scale_invariance_and_auto_e0() -> None:
    x = np.linspace(510.0, 560.0, 1001)
    a = normalize_edge_step(x, _edge(x))
    b = normalize_edge_step(x, 1e-10 * _edge(x))
    assert abs(a.e0 - 530.0) < 0.5  # steepest rise of an arctan edge
    np.testing.assert_allclose(a.y, b.y, atol=1e-9)


def test_edge_step_flatten_removes_post_edge_slope() -> None:
    x = np.linspace(510.0, 560.0, 1001)
    y = _edge(x, slope=-0.05)
    plain = normalize_edge_step(x, y, e0=530.0, post_degree=1)
    flat = normalize_edge_step(x, y, e0=530.0, post_degree=1, flatten=True)
    hi = x > 545
    assert np.ptp(flat.y[hi]) < 0.15 * np.ptp(plain.y[hi])
    np.testing.assert_allclose(flat.y[x <= 530.0], plain.y[x <= 530.0])


def test_edge_step_rejects_bad_windows_and_range() -> None:
    x = np.linspace(510.0, 560.0, 101)
    y = _edge(x)
    with pytest.raises(ValueError, match="outside the data range"):
        normalize_edge_step(x, y, e0=700.0)
    with pytest.raises(ValueError, match="must end below E0"):
        normalize_edge_step(x, y, e0=530.0, pre_max=535.0)
    with pytest.raises(ValueError, match="need at least"):
        normalize_edge_step(x, y, e0=530.0, pre_min=510.0, pre_max=510.2)
    with pytest.raises(ValueError, match="degree"):
        normalize_edge_step(x, y, e0=530.0, pre_degree=7)
    with pytest.raises(ValueError, match="edge step is zero"):
        normalize_edge_step(x, np.ones_like(x), e0=530.0)


def test_xas_normalize_registered_step_runs_on_xy() -> None:
    x = np.linspace(510.0, 560.0, 501)
    out = DEFAULT_STEPS["xas_normalize"].transform(XY(x=x, y=_edge(x)), {"e0": 530.0})
    assert out.y.shape == x.shape and np.array_equal(out.x, x)
    assert abs(out.y[-50:].mean() - 1.0) < 0.1
    # empty / blank params fall back to automatic choices
    auto = DEFAULT_STEPS["xas_normalize"].transform(XY(x=x, y=_edge(x)), {"e0": "", "pre_min": None})
    assert abs(auto.y[-50:].mean() - 1.0) < 0.1


def test_xas_fitting_uses_lmfit_engine() -> None:
    x = np.linspace(525.0, 540.0, 301)
    y = 3.0 * np.exp(-0.5 * ((x - 531.0) / 0.7) ** 2)
    y = y + np.random.default_rng(3).normal(0.0, 0.02, size=x.shape)
    problem = dict(
        x=x,
        y=y,
        components=[FitComponent(component_type="gaussian", component_id="pi_star")],
        p0=[530.5, 2.0, 1.0],  # gaussian parameter order: pos, amp, width
        bounds_lower=[528.0, 0.0, 0.1],
        bounds_upper=[534.0, 10.0, 3.0],
    )
    res = fit_curve(FitProblem(**problem, technique_family="xas"))
    assert abs(res.p_opt[0] - 531.0) < 0.05
    with pytest.raises(ValueError, match="Invalid technique_family"):
        fit_curve(FitProblem(**problem, technique_family="nmr"))


def _request(rel: str, **kw) -> DatasetCreateRequest:
    return DatasetCreateRequest(relative_paths=[rel], metadata=DatasetMetadata(name="t"), vms_spectrum_mode="all", **kw)


def test_mixed_sle_dataset_family_follows_selected_regions(tmp_path: Path) -> None:
    p = tmp_path / "mixed.sle"
    _write_sle(p)
    loaded = [("mixed.sle", p, load_dataset(p))]

    assert _dataset_family(loaded, _request("mixed.sle", xps_regions=["C1s", "VB_O"]), ["C1s", "VB_O"]) == "xps"
    xas_regions = ["OKedge_TEY", "OKedge_PEY"]
    assert _dataset_family(loaded, _request("mixed.sle", xps_regions=xas_regions), xas_regions) == "xas"
    # Explicit block indices work too (blocks 4 and 5 are the NEXAFS ones).
    req = _request("mixed.sle", record_indices={"mixed.sle": [4]})
    assert _dataset_family(loaded, req, None) == "xas"

    with pytest.raises(ValueError, match=r"Cannot mix .*XPS and XAS"):
        _dataset_family(loaded, _request("mixed.sle"), None)


def test_xps_only_multiblock_file_stays_xps(tmp_path: Path) -> None:
    p = tmp_path / "x.sle"
    _write_sle(p)
    loaded = [("x.sle", p, load_dataset(p))]
    assert _dataset_family(loaded, _request("x.sle", xps_regions=["C1s"]), ["C1s"]) == "xps"
