from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np

from sersflow.core.preprocess import fitting_models


BoundSide = float | None


@dataclass(frozen=True)
class ParamSpec:
    """
    Single source of truth for UI + fitting parameter ordering.

    Notes:
    - `key` must be stable because the frontend will persist user choices.
    - Ordering of `params` in a component defines the ordering in p0/bounds vectors.
    """

    key: str
    label: str
    default: float | None = None
    lower_default: BoundSide = None
    upper_default: BoundSide = None
    unit: str | None = None
    ui: dict[str, Any] | None = None


@dataclass(frozen=True)
class ComponentSpec:
    component_type: str
    display_name: str
    params: list[ParamSpec]
    kind: Literal["fixed", "parametric"] = "fixed"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "component_type": self.component_type,
            "display_name": self.display_name,
            "kind": self.kind,
            "params": [
                {
                    "key": p.key,
                    "label": p.label,
                    "default": p.default,
                    "bounds_default": {"lower": p.lower_default, "upper": p.upper_default},
                    "unit": p.unit,
                    "ui": p.ui or {},
                }
                for p in self.params
            ],
        }


def _gaussian_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="gaussian",
        display_name="Gaussian peak",
        params=[
            ParamSpec(
                key="pos",
                label="Center",
                default=None,
                lower_default=None,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.1},
            ),
            ParamSpec(
                key="amp",
                label="Amplitude",
                default=None,
                lower_default=0.0,
                upper_default=None,
                unit="a.u.",
                ui={"step": 1.0},
            ),
            ParamSpec(
                key="fwhm",
                label="FWHM",
                default=None,
                lower_default=1e-6,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.1, "min": 0.0},
            ),
        ],
    )


def polynomial_background_spec(degree: int) -> ComponentSpec:
    if degree < 0 or degree > 12:
        raise ValueError("degree must be in [0, 12]")
    # np.polyval expects highest degree first: cN ... c0
    params = []
    for d in range(degree, -1, -1):
        params.append(
            ParamSpec(
                key=f"c{d}",
                label=f"Coeff c{d}",
                default=0.0,
                lower_default=None,
                upper_default=None,
                unit=None,
                ui={"step": 0.01},
            )
        )
    return ComponentSpec(
        component_type="polynomial_background",
        display_name=f"Polynomial background (deg {degree})",
        params=params,
    )


def list_component_types() -> list[ComponentSpec]:
    # Parameterized specs (like polynomial degree) are represented via templates.
    # For the UI catalog we include a few common degrees.
    base = [_gaussian_spec()]
    base.extend(polynomial_background_spec(d) for d in (0, 1, 2, 3, 4))
    return base


def build_component_function(component_type: str, degree: int | None = None) -> tuple[Callable[..., np.ndarray], list[ParamSpec]]:
    """
    Return a callable f(x, *params) and the corresponding ordered ParamSpecs.
    """
    ct = component_type.strip().lower()
    if ct == "gaussian":
        spec = _gaussian_spec()
        return fitting_models.gaussian, spec.params
    if ct == "polynomial_background":
        if degree is None:
            raise ValueError("degree is required for polynomial_background")
        spec = polynomial_background_spec(int(degree))
        return fitting_models.polynomial_background, spec.params
    raise ValueError(f"Unknown component_type: {component_type}")

