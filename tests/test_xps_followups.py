"""Follow-up plan coverage: analytical LA area, dual Shirley, a_gl, guards, E2E."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.core.io.read_vms import VmsParseError, read_vms_blocks
from sersflow.core.pipeline.xps_background_guard import (
    assert_no_dual_xps_background,
    dual_xps_background_conflict,
)
from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_curve
from sersflow.core.preprocess.fitting_models import a_gl, gl
from sersflow.core.preprocess.fitting_specs import component_param_specs
from sersflow.core.preprocess.peak_area import (
    la_area_per_height_analytical,
    la_area_per_height_numeric,
)
from sersflow.core.xps.recipe_apply import apply_recipe_id


def test_la_analytical_matches_numeric_symmetric() -> None:
    a = la_area_per_height_analytical(1.0, 1.0, 1.0, 0.0)
    n = la_area_per_height_numeric(1.0, 1.0, 1.0, 0.0, n_points=16384, pad_widths=200.0)
    assert a == pytest.approx(math.pi / 2, rel=1e-6)
    assert a == pytest.approx(n, rel=1e-2)


def test_la_analytical_asymmetric_close_to_numeric() -> None:
    a = la_area_per_height_analytical(0.76, 1.1, 9.0, 0.0)
    n = la_area_per_height_numeric(0.76, 1.1, 9.0, 0.0, n_points=16384, pad_widths=200.0)
    assert a == pytest.approx(n, rel=5e-2)


def test_la_analytical_with_fwhm_g_finite() -> None:
    a0 = la_area_per_height_analytical(1.0, 1.2, 2.0, 0.0)
    a1 = la_area_per_height_analytical(1.0, 1.2, 2.0, 0.8)
    assert a1 > a0
    # FWHM_eff approx vs numeric convolution — order-of-magnitude / finite check only
    n = la_area_per_height_numeric(1.0, 1.2, 2.0, 0.8, n_points=8192)
    assert math.isfinite(n) and n > a0


def test_dual_shirley_conflict_detected() -> None:
    pipe = Pipeline(
        technique_family="xps",
        steps=[
            PipelineStep(name="baseline", params={"method": "shirley"}, enabled=True),
            PipelineStep(
                name="fitting",
                params={
                    "components": [{"component_id": "bg", "component_type": "shirley_bg"}],
                    "p0": [0.03, 0.0],
                    "bounds_lower": [0.0, None],
                    "bounds_upper": [None, None],
                },
                enabled=True,
            ),
        ],
    )
    msg = dual_xps_background_conflict(pipe.steps)
    assert msg and "Cannot combine" in msg
    with pytest.raises(ValueError, match="Cannot combine"):
        assert_no_dual_xps_background(pipe)


def test_dual_shirley_ok_when_only_active_bg() -> None:
    pipe = Pipeline(
        technique_family="xps",
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "components": [{"component_id": "bg", "component_type": "shirley_bg"}],
                    "p0": [0.03, 0.0],
                    "bounds_lower": [0.0, None],
                    "bounds_upper": [None, None],
                },
            )
        ],
    )
    assert dual_xps_background_conflict(pipe.steps) is None
    assert_no_dual_xps_background(pipe)


def test_a_gl_model_finite_and_recipe_applies() -> None:
    x = np.linspace(840.0, 870.0, 200)
    y = a_gl(x, 852.6, 100.0, 1.0, 30.0, 0.4, 0.55, 10.0)
    assert y.shape == x.shape
    assert np.all(np.isfinite(y))
    assert float(np.max(y)) == pytest.approx(100.0, rel=1e-2)

    out = apply_recipe_id("ni_2p32_metal_ref5", include_background=False)
    assert out["components"][0]["component_type"] == "a_gl"
    assert not any("not implemented" in w.lower() for w in out["warnings"])


def test_a_gl_lmfit_smoke() -> None:
    pytest.importorskip("lmfit")
    x = np.linspace(840.0, 870.0, 160)
    y = a_gl(x, 852.6, 80.0, 1.2, 30.0, 0.4, 0.55, 5.0)
    y = y + 5.0 * np.random.default_rng(0).normal(size=y.shape)
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[FitComponent(component_type="a_gl", component_id="p1")],
            p0=[852.0, 70.0, 1.0, 30.0, 0.4, 0.55, 5.0],
            bounds_lower=[840.0, 0.0, 1e-6, 0.0, 0.0, 0.0, 0.0],
            bounds_upper=[870.0, None, 8.0, 100.0, 5.0, 5.0, 40.0],
            technique_family="xps",
        )
    )
    assert res.y_hat.shape == x.shape
    assert np.all(np.isfinite(res.y_hat))


def test_prefer_pass_energy_from_acquisition() -> None:
    out = apply_recipe_id(
        "c_1s_adventitious",
        preferred_pass_energy=10,
        include_background=False,
    )
    assert out["recipe_pass_energy"] == 10


def test_lift_nxs_skip_summary_to_labels() -> None:
    from sersflow.core.io.multi_block_labels import lift_nxs_skip_summary_to_labels

    labels = {"sample": "x"}
    block_map = {
        "0": {
            "xps_region": "C1s",
            "nxs_skipped_count": 2,
            "nxs_skipped_regions": [{"key": "survey", "reason": "no_binding_energy"}],
        }
    }
    out = lift_nxs_skip_summary_to_labels(labels, block_map)
    assert out["nxs_skipped_count"] == 2
    assert len(out["nxs_skipped_regions"]) == 1
    assert labels == {"sample": "x"}  # original unchanged


def test_vms_block_meta_includes_pass_energy(tmp_path: Path) -> None:
    from tests.test_vms_loader import _legacy_block, _legacy_header
    from sersflow.core.io.read_vms import block_meta_dict, read_vms_blocks

    y = [1.0, 2.0, 3.0]
    lines = _legacy_header(n_blocks=1) + _legacy_block(
        block_name="C 1s_spectrum",
        species="C",
        transition="1s",
        x_start=290.0,
        x_step=-0.1,
        y=y,
    )
    path = tmp_path / "pe.vms"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _h, blocks = read_vms_blocks(path)
    meta = block_meta_dict(blocks[0])
    assert meta.get("pass_energy_eV") == 20.0


def test_vms_n_corr_vars_gt_1_raises(tmp_path: Path) -> None:
    from tests.test_vms_loader import _legacy_block, _legacy_header

    y = [10.0, 20.0, 30.0]
    block = _legacy_block(
        block_name="C 1s_spectrum",
        species="C",
        transition="1s",
        x_start=290.0,
        x_step=-0.1,
        y=y,
    )
    # n_corresponding_variables sits just before corr-var label "counts"
    text = "\n".join(_legacy_header(n_blocks=1) + block) + "\n"
    needle = "\n1\ncounts\n"
    assert needle in text
    text = text.replace(needle, "\n2\ncounts\n", 1)
    p = tmp_path / "multi_chan.vms"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(VmsParseError, match="n_corresponding_variables=2"):
        read_vms_blocks(p)


def test_golden_xps_vms_recipe_lmfit_observation(tmp_path: Path, monkeypatch) -> None:
    """VMS → XPS dataset → recipe apply → lmfit → feature/observation keys smoke."""
    pytest.importorskip("lmfit")
    from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
    from sersflow.api.services.datasets_service import create_dataset_from_uploads
    from sersflow.core.io.load_file import load_dataset
    from sersflow.core.models.datasets import MultiSpectrumDataset
    from tests.test_vms_loader import write_mixed_region_vms

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "e2e.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))

    batch = "e2e"
    dest = upload_root / batch / "mixed.vms"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_mixed_region_vms(dest)
    rel = f"{batch}/mixed.vms"

    ds_file = load_dataset(dest)
    assert isinstance(ds_file, MultiSpectrumDataset)
    assert any(str(m.get("xps_region")) == "C1s" for m in ds_file.meta)

    rec, skipped = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[rel],
            metadata=DatasetMetadata(name="xps-e2e", technique_family="xps"),
            vms_spectrum_mode="averages",
            xps_regions=["C1s"],
        ),
        owner_user_id="dev",
    )
    assert not skipped
    assert len(rec.spectra) == 1
    assert rec.metadata.technique_family == "xps"

    applied = apply_recipe_id("c_1s_adventitious", pass_energy=20, include_background=True)
    assert applied["components"][0]["component_type"] == "shirley_bg"
    assert applied["xps_region"] == "C1s"

    # Synthetic C1s-like spectrum on a dense BE grid matching recipe seeds.
    x = np.linspace(281.0, 291.0, 250)
    y = 40.0 + gl(x, 284.8, 800.0, 1.2, 30.0) + gl(x, 286.3, 200.0, 1.2, 30.0)
    y = y + 8.0 * np.random.default_rng(1).normal(size=y.shape)

    comps = [
        FitComponent(component_type=c["component_type"], component_id=c["component_id"])
        for c in applied["components"]
    ]
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=comps,
            p0=[float(v) for v in applied["p0"]],
            bounds_lower=list(applied["bounds_lower"]),
            bounds_upper=list(applied["bounds_upper"]),
            technique_family="xps",
            vary=list(applied["vary"]) if applied.get("vary") else None,
            param_links=list(applied.get("param_links") or []),
            initial_guess_mode="auto",
            xps_region=applied.get("xps_region"),
        )
    )
    assert res.y_hat.shape == x.shape
    assert np.all(np.isfinite(res.y_hat))

    feature_keys: list[str] = []
    for comp in comps:
        keys = [s.key for s in component_param_specs(comp.component_type)]
        for k in keys:
            feature_keys.append(f"fit_{applied.get('xps_region')}_{comp.component_id}_{k}")
    assert any(k.endswith("_pos") for k in feature_keys)
    assert any("_bg_" in k or k.endswith("_k") for k in feature_keys)
    assert float(np.corrcoef(y, res.y_hat)[0, 1]) > 0.5
