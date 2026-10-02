"""Tests for x_axis_calibration pipeline step."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sersflow.core.pipeline.engine import _run_indexed_steps_for_spectrum
from sersflow.core.pipeline.steps import DEFAULT_STEPS
from sersflow.core.preprocess.x_axis_calibration import (
    apply_x_axis_calibration,
    fitting_pos_keys_for_step,
)
from sersflow.core.spectrum import XY


def test_fixed_offset_shifts_x() -> None:
    xy = XY(x=np.array([100.0, 200.0, 300.0]), y=np.array([1.0, 2.0, 3.0]))
    out = DEFAULT_STEPS["x_axis_calibration"].transform(xy, {"method": "fixed_offset", "offset": -5.0})
    assert np.allclose(out.x, [95.0, 195.0, 295.0])
    assert np.array_equal(out.y, xy.y)


def test_fixed_offset_empty_passthrough() -> None:
    xy = XY(x=np.array([]), y=np.array([]))
    out = apply_x_axis_calibration(xy, {"method": "fixed_offset", "offset": 1.0})
    assert out.x.size == 0


def test_reference_peak_requires_measured_pos() -> None:
    xy = XY(x=np.array([1.0, 2.0]), y=np.array([1.0, 2.0]))
    with pytest.raises(ValueError, match="cohort precompute|_measured_pos"):
        apply_x_axis_calibration(
            xy, {"method": "reference_peak", "target_x": 284.8, "pos_key": "fit_g1_pos"}
        )


def test_fitting_pos_keys_include_xps_region() -> None:
    keys = fitting_pos_keys_for_step(
        {
            "xps_region": "C1s",
            "components": [{"component_id": "main", "component_type": "gaussian"}],
        },
        step_index=0,
        multi_fitting=False,
    )
    assert keys == ["fit_C1s_main_pos"]


def test_canonicalize_strips_multi_fit_prefix() -> None:
    from sersflow.core.preprocess.x_axis_calibration import canonicalize_calibration_pos_key

    assert (
        canonicalize_calibration_pos_key("s1_fit_C1s_C_C_C_H_alkyl_adventitious_pos")
        == "fit_C1s_C_C_C_H_alkyl_adventitious_pos"
    )
    assert canonicalize_calibration_pos_key("fit_g1_pos") == "fit_g1_pos"


def test_reference_peak_accepts_legacy_multi_fit_pos_key() -> None:
    """UI used to save s{N}_-prefixed keys when multiple fittings exist; engine must accept them."""
    true_pos = 290.0
    target = 284.8
    x = np.linspace(270.0, 310.0, 200)
    y = 80.0 * np.exp(-((x - true_pos) ** 2) / (8.0**2 / 4.0 / np.log(2.0))) + 2.0
    xy0 = XY(x=x, y=y)
    fit_c1s = "fit-c1s"
    fit_o1s = "fit-o1s"
    steps = [
        {
            "name": "fitting",
            "step_id": fit_c1s,
            "enabled": True,
            "params": {
                "output_mode": "fit",
                "xps_region": "C1s",
                "components": [{"component_id": "g1", "component_type": "gaussian"}],
                "p0": [289.0, 70.0, 10.0],
                "bounds_lower": [275.0, 0.0, 1e-6],
                "bounds_upper": [305.0, None, 40.0],
            },
        },
        {
            "name": "x_axis_calibration",
            "step_id": "cal-1",
            "enabled": True,
            "params": {
                "method": "reference_peak",
                "fitting_step_id": fit_c1s,
                # Legacy multi-fitting feature-export name (UI used s{N}_ when ≥2 fittings).
                "pos_key": "s1_fit_C1s_g1_pos",
                "target_x": target,
            },
        },
        {
            "name": "fitting",
            "step_id": fit_o1s,
            "enabled": True,
            "params": {
                "output_mode": "fit",
                "xps_region": "O1s",
                "components": [{"component_id": "o1", "component_type": "gaussian"}],
                "p0": [532.0, 1.0, 10.0],
            },
        },
    ]
    final, _, _ = _run_indexed_steps_for_spectrum(
        xy_initial=xy0,
        input_hash="testhash",
        steps_list=steps,
        spectrum_id="sid",
        cache=None,
        namespace="ns",
        up_to_step=None,
        collect_steps=None,
        technique_family="xps",
        spectrum_xps_region="C1s",
    )
    expected_delta = target - true_pos
    assert float(final.x[0] - xy0.x[0]) == pytest.approx(expected_delta, abs=0.5)


def test_reference_peak_pipeline_shifts_to_target() -> None:
    true_pos = 290.0
    target = 284.8
    x = np.linspace(270.0, 310.0, 200)
    y = 80.0 * np.exp(-((x - true_pos) ** 2) / (8.0**2 / 4.0 / np.log(2.0))) + 2.0
    xy0 = XY(x=x, y=y)
    fit_id = "fit-step-1"
    steps = [
        {
            "name": "fitting",
            "step_id": fit_id,
            "enabled": True,
            "params": {
                "output_mode": "fit",
                "components": [{"component_id": "g1", "component_type": "gaussian"}],
                "p0": [289.0, 70.0, 10.0],
                "bounds_lower": [275.0, 0.0, 1e-6],
                "bounds_upper": [305.0, None, 40.0],
            },
        },
        {
            "name": "x_axis_calibration",
            "step_id": "cal-1",
            "enabled": True,
            "params": {
                "method": "reference_peak",
                "fitting_step_id": fit_id,
                "pos_key": "fit_g1_pos",
                "target_x": target,
            },
        },
    ]
    final, _, _ = _run_indexed_steps_for_spectrum(
        xy_initial=xy0,
        input_hash="testhash",
        steps_list=steps,
        spectrum_id="sid",
        cache=None,
        namespace="ns",
        up_to_step=None,
        collect_steps=None,
    )
    # After calibration, the fitted peak on the shifted axis should sit near target.
    # Re-fit final spectrum with same model / shifted initial guess.
    from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params

    params = {
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [target, 70.0, 10.0],
        "bounds_lower": [target - 15.0, 0.0, 1e-6],
        "bounds_upper": [target + 15.0, None, 40.0],
    }
    # Fitting step replaced y with model; recalibrate applies to that XY's x.
    # Check that original peak position shifted by (target - measured) ≈ target on axis.
    expected_delta = target - true_pos
    assert float(final.x[0] - xy0.x[0]) == pytest.approx(expected_delta, abs=0.5)
    prob = fit_problem_from_step_params(final, params)
    assert prob is not None
    res = fit_curve(prob)
    fitted_pos = float(res.p_opt[0])
    assert fitted_pos == pytest.approx(target, abs=0.5)


def test_reference_peak_missing_fitting_step_id() -> None:
    xy0 = XY(x=np.linspace(0.0, 10.0, 20), y=np.ones(20))
    steps = [
        {
            "name": "x_axis_calibration",
            "enabled": True,
            "params": {"method": "reference_peak", "pos_key": "fit_g1_pos", "target_x": 1.0},
        },
    ]
    with pytest.raises(ValueError, match="fitting_step_id"):
        _run_indexed_steps_for_spectrum(
            xy_initial=xy0,
            input_hash="h",
            steps_list=steps,
            spectrum_id="sid",
            cache=None,
            namespace="ns",
            up_to_step=None,
            collect_steps=None,
        )


def test_reference_peak_unknown_pos_key() -> None:
    fit_id = "fit-1"
    x = np.linspace(400.0, 600.0, 100)
    y = 50.0 * np.exp(-((x - 500.0) ** 2) / (10.0**2 / 4.0 / np.log(2.0)))
    steps = [
        {
            "name": "fitting",
            "step_id": fit_id,
            "enabled": True,
            "params": {
                "components": [{"component_id": "g1", "component_type": "gaussian"}],
                "p0": [500.0, 40.0, 12.0],
                "bounds_lower": [400.0, 0.0, 1e-6],
                "bounds_upper": [600.0, None, 80.0],
            },
        },
        {
            "name": "x_axis_calibration",
            "enabled": True,
            "params": {
                "method": "reference_peak",
                "fitting_step_id": fit_id,
                "pos_key": "fit_missing_pos",
                "target_x": 510.0,
            },
        },
    ]
    with pytest.raises(ValueError, match="pos_key"):
        _run_indexed_steps_for_spectrum(
            xy_initial=XY(x=x, y=y),
            input_hash="h",
            steps_list=steps,
            spectrum_id="sid",
            cache=None,
            namespace="ns",
            up_to_step=None,
            collect_steps=None,
        )


def test_reference_peak_fitting_must_be_earlier() -> None:
    fit_id = "fit-later"
    steps = [
        {
            "name": "x_axis_calibration",
            "enabled": True,
            "params": {
                "method": "reference_peak",
                "fitting_step_id": fit_id,
                "pos_key": "fit_g1_pos",
                "target_x": 500.0,
            },
        },
        {
            "name": "fitting",
            "step_id": fit_id,
            "enabled": True,
            "params": {
                "components": [{"component_id": "g1", "component_type": "gaussian"}],
                "p0": [500.0, 1.0, 10.0],
            },
        },
    ]
    with pytest.raises(ValueError, match="earlier"):
        _run_indexed_steps_for_spectrum(
            xy_initial=XY(x=np.linspace(400.0, 600.0, 50), y=np.ones(50)),
            input_hash="h",
            steps_list=steps,
            spectrum_id="sid",
            cache=None,
            namespace="ns",
            up_to_step=None,
            collect_steps=None,
        )



def test_normalize_region_and_vb_partner() -> None:
    from sersflow.core.preprocess.x_axis_calibration import (
        is_valence_band_region_name,
        is_valence_partner_for_region,
        normalize_region_token,
        regions_match,
    )

    assert normalize_region_token("O 1s") == "o1s"
    assert normalize_region_token("O_1s") == "o1s"
    assert regions_match("C1s", "c 1s")
    assert is_valence_band_region_name("VB")
    assert is_valence_partner_for_region("vb-O1s", "O 1s")
    assert is_valence_partner_for_region("fermi_O1s", "O1s")
    assert not is_valence_partner_for_region("vb-C1s", "O1s")


def test_single_reference_band_averages_and_applies_to_all() -> None:
    from sersflow.core.preprocess.x_axis_calibration import compute_calibration_deltas_for_step

    measured = {"a": 290.0, "b": 292.0, "c": 500.0}
    labels = {
        "a": {"xps_region": "C1s", "sample": "1"},
        "b": {"xps_region": "C1s", "sample": "1"},
        "c": {"xps_region": "O1s", "sample": "1"},
    }

    def measure(sid: str, _fp: dict, _pk: str) -> float:
        return measured[sid]

    out = compute_calibration_deltas_for_step(
        spectrum_ids=["a", "b", "c"],
        labels_by_id=labels,
        cal_params={
            "method": "single_reference_band",
            "pos_key": "fit_g1_pos",
            "target_x": 284.8,
            "reference_filters": [{"field": "xps_region", "op": "in", "values": ["C1s"]}],
        },
        fit_params={"xps_region": "C1s", "components": [{"component_id": "g1", "component_type": "gaussian"}]},
        measure=measure,
    )
    # mean measured = 291.0 → delta = 284.8 - 291 = -6.2 for everyone
    assert out.deltas["a"] == pytest.approx(-6.2)
    assert out.deltas["b"] == pytest.approx(-6.2)
    assert out.deltas["c"] == pytest.approx(-6.2)
    assert any("averaging" in w for w in out.warnings)


def test_grouped_core_level_per_group_offset() -> None:
    from sersflow.core.preprocess.x_axis_calibration import compute_calibration_deltas_for_step

    measured = {"c1s_a": 290.0, "o1s_a": 532.0, "c1s_b": 288.0, "o1s_b": 531.0}
    labels = {
        "c1s_a": {"xps_region": "C1s", "run": "A"},
        "o1s_a": {"xps_region": "O1s", "run": "A"},
        "c1s_b": {"xps_region": "C1s", "run": "B"},
        "o1s_b": {"xps_region": "O1s", "run": "B"},
    }

    def measure(sid: str, _fp: dict, _pk: str) -> float:
        return measured[sid]

    out = compute_calibration_deltas_for_step(
        spectrum_ids=list(labels),
        labels_by_id=labels,
        cal_params={
            "method": "grouped_reference_band",
            "group_by": "run",
            "reference_mode": "core_level",
            "reference_region": "C1s",
            "pos_key": "fit_g1_pos",
            "target_x": 284.8,
        },
        fit_params={"xps_region": "C1s", "components": [{"component_id": "g1", "component_type": "gaussian"}]},
        measure=measure,
    )
    assert out.deltas["o1s_a"] == pytest.approx(284.8 - 290.0)
    assert out.deltas["c1s_a"] == pytest.approx(284.8 - 290.0)
    assert out.deltas["o1s_b"] == pytest.approx(284.8 - 288.0)


def test_grouped_valence_pairs_and_warns_unpaired() -> None:
    from sersflow.core.preprocess.x_axis_calibration import compute_calibration_deltas_for_step

    measured = {"vb_o": 0.4, "o1s": 532.0, "n1s": 400.0}
    labels = {
        "vb_o": {"xps_region": "vb-O1s", "run": "1"},
        "o1s": {"xps_region": "O1s", "run": "1"},
        "n1s": {"xps_region": "N1s", "run": "1"},
    }

    def measure(sid: str, _fp: dict, _pk: str) -> float:
        return measured[sid]

    out = compute_calibration_deltas_for_step(
        spectrum_ids=list(labels),
        labels_by_id=labels,
        cal_params={
            "method": "grouped_reference_band",
            "group_by": "run",
            "reference_mode": "valence_band",
            "pos_key": "fit_Fermi_edge_center",
            "target_x": 0.0,
        },
        fit_params={
            "xps_region": "valence band",
            "components": [{"component_id": "Fermi_edge", "component_type": "fermi_edge"}],
        },
        measure=measure,
    )
    assert out.deltas["o1s"] == pytest.approx(-0.4)
    assert out.deltas["vb_o"] == pytest.approx(-0.4)
    assert out.deltas["n1s"] == 0.0
    assert any("no VB partner" in w for w in out.warnings)


def test_grouped_core_missing_reference_warns() -> None:
    from sersflow.core.preprocess.x_axis_calibration import compute_calibration_deltas_for_step

    labels = {
        "o1s": {"xps_region": "O1s", "run": "1"},
    }

    def measure(_sid: str, _fp: dict, _pk: str) -> float:
        raise AssertionError("should not measure")

    out = compute_calibration_deltas_for_step(
        spectrum_ids=["o1s"],
        labels_by_id=labels,
        cal_params={
            "method": "grouped_reference_band",
            "group_by": "run",
            "reference_mode": "core_level",
            "reference_region": "C1s",
            "pos_key": "fit_g1_pos",
            "target_x": 284.8,
        },
        fit_params={"xps_region": "C1s"},
        measure=measure,
    )
    assert out.deltas["o1s"] == 0.0
    assert any("missing" in w.lower() for w in out.warnings)


def test_fixed_offset_via_pipeline() -> None:
    xy0 = XY(x=np.array([10.0, 20.0]), y=np.array([1.0, 2.0]))
    final, _, _ = _run_indexed_steps_for_spectrum(
        xy_initial=xy0,
        input_hash="h",
        steps_list=[
            {
                "name": "x_axis_calibration",
                "enabled": True,
                "params": {"method": "fixed_offset", "offset": 3.5},
            }
        ],
        spectrum_id="sid",
        cache=None,
        namespace="ns",
        up_to_step=None,
        collect_steps=None,
    )
    assert np.allclose(final.x, [13.5, 23.5])
    assert math.isfinite(float(final.y[0]))

