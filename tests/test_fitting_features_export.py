from __future__ import annotations

import math

import numpy as np
import pytest

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.core.metrics.fitting_features import (
    collect_fitting_features_for_pipeline,
    gaussian_peak_area,
    lorentzian_peak_area,
    preview_fitting_feature_keys_for_pipeline,
    pseudo_voigt_peak_area,
    voigt_peak_area,
)
from sersflow.core.spectrum import XY


def test_gaussian_peak_area_matches_numeric_integral() -> None:
    """Area under fitting_models.gaussian (same parameterization as fit)."""
    pos, amp, fwhm = 500.0, 100.0, 20.0
    x = np.linspace(400.0, 600.0, 20_001)
    y = amp * np.exp(-(np.power(x - pos, 2) / (fwhm * fwhm / 4.0 / np.log(2.0))))
    num = float(np.trapezoid(y, x))
    ana = gaussian_peak_area(amp, fwhm)
    assert ana == pytest.approx(num, rel=1e-4)


def test_lorentzian_peak_area_matches_numeric_integral() -> None:
    pos, amp, fwhm = 500.0, 100.0, 20.0
    # Heavy tails: integrate far from center.
    x = np.linspace(pos - 50_000.0, pos + 50_000.0, 200_001)
    y = amp / (1.0 + 4.0 * ((x - pos) / fwhm) ** 2)
    num = float(np.trapezoid(y, x))
    ana = lorentzian_peak_area(amp, fwhm)
    assert ana == pytest.approx(num, rel=1e-3)


def test_pseudo_voigt_peak_area_matches_mix() -> None:
    amp, fwhm, eta = 50.0, 15.0, 0.3
    expected = eta * lorentzian_peak_area(amp, fwhm) + (1.0 - eta) * gaussian_peak_area(amp, fwhm)
    assert pseudo_voigt_peak_area(amp, fwhm, eta) == pytest.approx(expected)


def test_voigt_peak_area_matches_numeric_integral() -> None:
    from sersflow.core.preprocess.fitting_models import voigt

    pos, amp, fwhm_g, fwhm_l = 500.0, 80.0, 12.0, 8.0
    x = np.linspace(pos - 50_000.0, pos + 50_000.0, 200_001)
    y = voigt(x, pos, amp, fwhm_g, fwhm_l)
    num = float(np.trapezoid(y, x))
    ana = voigt_peak_area(amp, fwhm_g, fwhm_l)
    assert ana == pytest.approx(num, rel=1e-3)


def test_preview_fitting_keys_gaussian_component() -> None:
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "components": [{"component_id": "g1", "component_type": "gaussian"}],
                    "p0": [500.0, 1.0, 10.0],
                    "bounds_lower": [400.0, 0.0, 1e-6],
                    "bounds_upper": [600.0, None, 80.0],
                },
            ),
        ]
    )
    keys = preview_fitting_feature_keys_for_pipeline(pipe)
    assert keys == ["fit_g1_pos", "fit_g1_amp", "fit_g1_fwhm", "fit_g1_area"]


def test_preview_fitting_keys_lorentzian_and_voigt() -> None:
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "components": [
                        {"component_id": "l1", "component_type": "lorentzian"},
                        {"component_id": "v1", "component_type": "voigt"},
                        {"component_id": "pv1", "component_type": "pseudo_voigt"},
                    ],
                    "p0": [500.0, 1.0, 10.0, 500.0, 1.0, 8.0, 6.0, 500.0, 1.0, 10.0, 0.5],
                    "bounds_lower": [None] * 11,
                    "bounds_upper": [None] * 11,
                },
            ),
        ]
    )
    keys = preview_fitting_feature_keys_for_pipeline(pipe)
    assert keys == [
        "fit_l1_pos",
        "fit_l1_amp",
        "fit_l1_fwhm",
        "fit_l1_area",
        "fit_v1_pos",
        "fit_v1_amp",
        "fit_v1_fwhm_g",
        "fit_v1_fwhm_l",
        "fit_v1_area",
        "fit_pv1_pos",
        "fit_pv1_amp",
        "fit_pv1_fwhm",
        "fit_pv1_eta",
        "fit_pv1_area",
    ]


def test_preview_fitting_keys_include_polynomial_coefficients() -> None:
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "components": [
                        {"component_id": "bg", "component_type": "polynomial_background", "degree": 2}
                    ],
                    "p0": [0.1, 0.2, 0.3],
                    "bounds_lower": [None, None, None],
                    "bounds_upper": [None, None, None],
                },
            ),
        ]
    )
    keys = preview_fitting_feature_keys_for_pipeline(pipe)
    assert keys == ["fit_bg_c2", "fit_bg_c1", "fit_bg_c0"]


def test_collect_fitting_features_populates_gaussian_params() -> None:
    x = np.linspace(400.0, 600.0, 200)
    y = 80.0 * np.exp(-((x - 510.0) ** 2) / (12.0**2 / 4.0 / np.log(2.0))) + 0.5
    xy = XY(x=x, y=y)
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "output_mode": "fit",
                    "components": [{"component_id": "pk", "component_type": "gaussian"}],
                    "p0": [500.0, 70.0, 12.0],
                    "bounds_lower": [400.0, 0.0, 1e-6],
                    "bounds_upper": [600.0, None, 40.0],
                },
            ),
        ]
    )
    ordered, feats = collect_fitting_features_for_pipeline(xy, pipe)
    assert "fit_pk_pos" in feats
    assert feats["fit_pk_pos"] is not None
    assert abs(float(feats["fit_pk_pos"]) - 510.0) < 5.0
    assert feats["fit_pk_area"] is not None
    assert math.isfinite(float(feats["fit_pk_area"]))


def test_collect_fitting_features_populates_polynomial_coefficients() -> None:
    x = np.linspace(-2.0, 2.0, 80)
    y = 2.0 * x**2 - 0.5 * x + 3.0
    xy = XY(x=x, y=y)
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "output_mode": "fit",
                    "components": [
                        {"component_id": "bg", "component_type": "polynomial_background", "degree": 2}
                    ],
                    "p0": [1.0, 0.0, 1.0],
                    "bounds_lower": [None, None, None],
                    "bounds_upper": [None, None, None],
                },
            ),
        ]
    )

    ordered, feats = collect_fitting_features_for_pipeline(xy, pipe)

    assert ordered == ["fit_bg_c2", "fit_bg_c1", "fit_bg_c0"]
    assert feats["fit_bg_c2"] == pytest.approx(2.0, abs=1e-8)
    assert feats["fit_bg_c1"] == pytest.approx(-0.5, abs=1e-8)
    assert feats["fit_bg_c0"] == pytest.approx(3.0, abs=1e-8)

