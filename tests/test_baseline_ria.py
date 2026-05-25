from __future__ import annotations

import sys
import types
from typing import Any

import numpy as np

from sersflow.core.pipeline import steps as pipeline_steps
from sersflow.core.preprocess.baseline import (
    BASELINE_METHODS,
    baseline_method_metadata,
    baseline_signature_drift,
    correct_baseline,
)
from sersflow.core.spectrum import XY


def test_correct_baseline_ria_forwards_pybaselines_options(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeBaseline:
        def ria(self, intensity, **kwargs):
            calls.append(
                {
                    "intensity": np.asarray(intensity, dtype=float),
                    **kwargs,
                }
            )
            return np.asarray([1.0, 2.0, 3.0], dtype=float), {"method": "ria"}

    monkeypatch.setitem(sys.modules, "pybaselines", types.SimpleNamespace(Baseline=FakeBaseline))

    intensity = np.asarray([10.0, 20.0, 30.0], dtype=float)
    corrected, params = correct_baseline(
        intensity,
        method="ria",
        half_window=6,
        width_scale=1,
        height_scale=2,
    )

    np.testing.assert_allclose(corrected, np.asarray([9.0, 18.0, 27.0]))
    assert params["method"] == "ria"
    np.testing.assert_allclose(params["baseline"], np.asarray([1.0, 2.0, 3.0]))
    assert len(calls) == 1
    np.testing.assert_allclose(calls[0]["intensity"], intensity)
    assert calls[0]["half_window"] == 6
    assert calls[0]["width_scale"] == 1.0
    assert calls[0]["height_scale"] == 2.0
    assert calls[0]["side"] == "both"


def test_pipeline_baseline_step_forwards_ria_options(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_correct_baseline(intensity, method="derpsalsa", **kwargs):
        captured["method"] = method
        captured["kwargs"] = kwargs
        baseline = np.asarray([1.0, 1.0, 1.0], dtype=float)
        return np.asarray(intensity, dtype=float) - baseline, {"baseline": baseline}

    monkeypatch.setattr(pipeline_steps, "correct_baseline", fake_correct_baseline)

    xy = XY(x=np.asarray([1.0, 2.0, 3.0]), y=np.asarray([10.0, 20.0, 30.0]))
    out = pipeline_steps.DEFAULT_STEPS["baseline"].transform(
        xy,
        {"method": "ria", "half_window": 6, "width_scale": 1, "height_scale": 2},
    )

    np.testing.assert_allclose(out.y, np.asarray([9.0, 19.0, 29.0]))
    assert captured == {
        "method": "ria",
        "kwargs": {
            "half_window": 6,
            "max_iter": 500,
            "tol": 0.01,
            "side": "both",
            "width_scale": 1.0,
            "height_scale": 2.0,
            "sigma_scale": 1.0 / 12.0,
            "pad_kwargs": None,
        },
    }


def test_all_catalog_methods_dispatch_through_generic_path(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeBaseline:
        def __getattr__(self, name: str):
            def method(intensity, **kwargs):
                calls.append((name, kwargs))
                return np.zeros_like(np.asarray(intensity, dtype=float)), {"method": name}

            return method

    monkeypatch.setitem(sys.modules, "pybaselines", types.SimpleNamespace(Baseline=FakeBaseline))

    intensity = np.asarray([1.0, 2.0, 3.0], dtype=float)
    for method in BASELINE_METHODS:
        corrected, params = correct_baseline(intensity, method=method)
        np.testing.assert_allclose(corrected, intensity)
        assert params["method"] == method

    assert [name for name, _ in calls] == list(BASELINE_METHODS)


def test_baseline_metadata_contains_categories_descriptions_and_null_defaults() -> None:
    meta = baseline_method_metadata()
    categories = {c["id"] for c in meta["categories"]}
    assert {"whittaker", "smoothing", "splines", "polynomial", "morphological", "miscellaneous"} <= categories

    methods = {m["id"]: m for m in meta["methods"]}
    assert methods["mormol"]["category"] == "morphological"
    half_window = next(p for p in methods["mormol"]["params"] if p["key"] == "half_window")
    assert half_window["nullable"] is True
    assert half_window["default"] is None
    assert "window" in half_window["description"].lower()


def test_baseline_signature_catalog_matches_installed_pybaselines() -> None:
    assert baseline_signature_drift() == []
