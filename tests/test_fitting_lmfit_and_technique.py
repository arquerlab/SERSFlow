from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_curve
from sersflow.core.preprocess.fitting_specs import XPS_BACKGROUND_COMPONENT_TYPES, list_component_types


def test_registry_includes_xps_backgrounds() -> None:
    types = {s.component_type for s in list_component_types()}
    assert XPS_BACKGROUND_COMPONENT_TYPES <= types


def test_vibrational_engine_rejects_xps_background() -> None:
    x = np.linspace(0.0, 10.0, 40)
    y = np.ones_like(x)
    with pytest.raises(ValueError, match="XPS pipeline"):
        fit_curve(
            FitProblem(
                x=x,
                y=y,
                components=[FitComponent(component_type="shirley_bg", component_id="bg")],
                p0=[0.03, 0.0],
                bounds_lower=[0.0, None],
                bounds_upper=[None, None],
                technique_family="vibrational",
            )
        )


def test_vibrational_engine_rejects_param_links() -> None:
    x = np.linspace(480.0, 560.0, 80)
    y = np.exp(-((x - 520.0) ** 2) / 50.0)
    with pytest.raises(ValueError, match="Parameter links"):
        fit_curve(
            FitProblem(
                x=x,
                y=y,
                components=[
                    FitComponent(component_type="gaussian", component_id="a"),
                    FitComponent(component_type="gaussian", component_id="b"),
                ],
                p0=[520.0, 1.0, 10.0, 530.0, 1.0, 10.0],
                bounds_lower=[400.0, 0.0, 1e-6, 400.0, 0.0, 1e-6],
                bounds_upper=[600.0, None, 80.0, 600.0, None, 80.0],
                technique_family="vibrational",
                param_links=[
                    {
                        "source_component_id": "b",
                        "source_key": "fwhm",
                        "target_component_id": "a",
                        "target_key": "fwhm",
                        "mode": "equal",
                    }
                ],
            )
        )


def test_vibrational_uses_curve_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"scipy": False}
    import sersflow.core.preprocess.fitting as fitting_mod

    real = fitting_mod._fit_curve_scipy

    def spy(problem):
        called["scipy"] = True
        return real(problem)

    monkeypatch.setattr(fitting_mod, "_fit_curve_scipy", spy)

    x = np.linspace(480.0, 560.0, 100)
    y = 50.0 * np.exp(-((x - 520.0) ** 2) / (10.0**2 / 4.0 / np.log(2.0)))
    fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[FitComponent(component_type="gaussian", component_id="p1")],
            p0=[518.0, 40.0, 12.0],
            bounds_lower=[500.0, 0.0, 1e-6],
            bounds_upper=[540.0, None, 40.0],
            technique_family="vibrational",
        )
    )
    assert called["scipy"] is True


def test_xps_routes_to_lmfit(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("lmfit")
    called = {"lmfit": False}

    import sersflow.core.preprocess.fitting_lmfit as lm

    real = lm.fit_curve_lmfit

    def spy(problem):
        called["lmfit"] = True
        return real(problem)

    monkeypatch.setattr(lm, "fit_curve_lmfit", spy)

    x = np.linspace(480.0, 560.0, 100)
    y = 50.0 * np.exp(-((x - 520.0) ** 2) / (10.0**2 / 4.0 / np.log(2.0)))
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[FitComponent(component_type="gaussian", component_id="p1")],
            p0=[518.0, 40.0, 12.0],
            bounds_lower=[500.0, 0.0, 1e-6],
            bounds_upper=[540.0, None, 40.0],
            technique_family="xps",
        )
    )
    assert called["lmfit"] is True
    assert res.p_opt.shape == (3,)


def test_xps_param_link_equal_smoke() -> None:
    pytest.importorskip("lmfit")
    x = np.linspace(480.0, 560.0, 120)
    y1 = 80.0 * np.exp(-((x - 510.0) ** 2) / (12.0**2 / 4.0 / np.log(2.0)))
    y2 = 40.0 * np.exp(-((x - 540.0) ** 2) / (12.0**2 / 4.0 / np.log(2.0)))
    y = y1 + y2
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[
                FitComponent(component_type="gaussian", component_id="a"),
                FitComponent(component_type="gaussian", component_id="b"),
            ],
            p0=[510.0, 70.0, 14.0, 540.0, 35.0, 14.0],
            bounds_lower=[480.0, 0.0, 1e-6, 480.0, 0.0, 1e-6],
            bounds_upper=[560.0, None, 40.0, 560.0, None, 40.0],
            technique_family="xps",
            param_links=[
                {
                    "source_component_id": "b",
                    "source_key": "fwhm",
                    "target_component_id": "a",
                    "target_key": "fwhm",
                    "mode": "equal",
                }
            ],
        )
    )
    assert abs(float(res.p_opt[2]) - float(res.p_opt[5])) < 1e-6


def test_xps_param_link_offset_smoke() -> None:
    pytest.importorskip("lmfit")
    x = np.linspace(480.0, 560.0, 160)
    y1 = 80.0 * np.exp(-((x - 510.0) ** 2) / (12.0**2 / 4.0 / np.log(2.0)))
    y2 = 40.0 * np.exp(-((x - 525.0) ** 2) / (12.0**2 / 4.0 / np.log(2.0)))
    y = y1 + y2
    delta = 15.0
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[
                FitComponent(component_type="gaussian", component_id="a"),
                FitComponent(component_type="gaussian", component_id="b"),
            ],
            p0=[510.0, 70.0, 14.0, 525.0, 35.0, 14.0],
            bounds_lower=[480.0, 0.0, 1e-6, 480.0, 0.0, 1e-6],
            bounds_upper=[560.0, None, 40.0, 560.0, None, 40.0],
            technique_family="xps",
            param_links=[
                {
                    "source_component_id": "b",
                    "source_key": "pos",
                    "target_component_id": "a",
                    "target_key": "pos",
                    "mode": "offset",
                    "offset": delta,
                }
            ],
        )
    )
    assert abs(float(res.p_opt[3]) - (float(res.p_opt[0]) + delta)) < 1e-5


def test_xps_shirley_bg_smoke() -> None:
    pytest.importorskip("lmfitxps")
    # Descending BE axis (typical XPS) with a peak on a step-like background.
    x = np.linspace(300.0, 280.0, 80)
    y = np.linspace(5.0, 15.0, 80) + 40.0 * np.exp(-((x - 290.0) ** 2) / 8.0)
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[
                FitComponent(component_type="shirley_bg", component_id="bg"),
                FitComponent(component_type="gaussian", component_id="p1"),
            ],
            p0=[0.03, 0.0, 290.0, 30.0, 2.0],
            bounds_lower=[0.0, None, 285.0, 0.0, 0.1],
            bounds_upper=[1.0, None, 295.0, None, 10.0],
            technique_family="xps",
        )
    )
    assert res.p_opt.shape == (5,)
    assert len(res.component_y_hat) == 2


def test_fitting_fit_api_accepts_shirley_bg_when_xps() -> None:
    """Regression: /fitting/fit must not call build_component_function for XPS BGs."""
    pytest.importorskip("lmfitxps")
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    x = np.linspace(300.0, 280.0, 60).tolist()
    y = (np.linspace(5.0, 15.0, 60) + 40.0 * np.exp(-((np.asarray(x) - 290.0) ** 2) / 8.0)).tolist()
    client = TestClient(app)
    r = client.post(
        "/fitting/fit",
        json={
            "target": {"kind": "inline", "x": x, "y": y},
            "components": [
                {"component_id": "bg", "component_type": "shirley_bg"},
                {"component_id": "p1", "component_type": "gaussian"},
            ],
            "p0": [0.03, 0.0, 290.0, 30.0, 2.0],
            "bounds": {
                "lower": [0.0, None, 285.0, 0.0, 0.1],
                "upper": [1.0, None, 295.0, None, 10.0],
            },
            "return_curve": True,
            "technique_family": "xps",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["params_vector"]) == 5
    assert body["components"][0]["component_type"] == "shirley_bg"
    assert body["y_hat"] is not None
    assert len(body["y_hat"]) == len(x)
