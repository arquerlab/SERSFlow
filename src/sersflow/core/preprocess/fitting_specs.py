from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np

from sersflow.core.preprocess import fitting_models


BoundSide = float | None

# Peak shapes that share position + height amplitude (auto initial-guess applies).
PEAK_COMPONENT_TYPES = frozenset(
    {
        "gaussian",
        "lorentzian",
        "pseudo_voigt",
        "gl",
        "voigt",
        "ds",
        "gds",
        "la",
        "lf",
        "a_gl",
        "apv",
        "asymmetric_voigt",
    }
)

# Ideal DS / GDS tails are non-integrable for alpha > 0 — do not export area.
INFINITE_AREA_COMPONENT_TYPES = frozenset({"ds", "gds"})

# Peaks that export a derived area column (analytical or numeric).
AREA_EXPORT_COMPONENT_TYPES = PEAK_COMPONENT_TYPES - INFINITE_AREA_COMPONENT_TYPES

XPS_BACKGROUND_COMPONENT_TYPES = frozenset({"shirley_bg", "tougaard_bg", "slope_bg"})

# lmfitxps models that are not simple peak callables (XPS pipelines only).
XPS_LMFITXPS_COMPONENT_TYPES = XPS_BACKGROUND_COMPONENT_TYPES | frozenset({"fermi_edge"})

# Boltzmann constant in eV/K (for Temperature → kt conversion).
BOLTZMANN_EV_PER_K = 8.617333262145e-5


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


def _peak_pos_amp_params() -> list[ParamSpec]:
    return [
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
    ]


def _fwhm_param(*, key: str = "fwhm", label: str = "FWHM", default: float | None = None) -> ParamSpec:
    return ParamSpec(
        key=key,
        label=label,
        default=default,
        lower_default=1e-6,
        upper_default=None,
        unit="cm^-1",
        ui={"step": 0.1, "min": 0.0},
    )


def _gaussian_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="gaussian",
        display_name="Gaussian peak",
        params=[*_peak_pos_amp_params(), _fwhm_param()],
    )


def _lorentzian_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="lorentzian",
        display_name="Lorentzian peak",
        params=[*_peak_pos_amp_params(), _fwhm_param()],
    )


def _pseudo_voigt_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="pseudo_voigt",
        display_name="Pseudo-Voigt peak",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(),
            ParamSpec(
                key="eta",
                label="Lorentzian fraction (η)",
                default=0.5,
                lower_default=0.0,
                upper_default=1.0,
                unit=None,
                ui={"step": 0.01, "min": 0.0, "max": 1.0},
            ),
        ],
    )


def _gl_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="gl",
        display_name="Gaussian–Lorentzian sum (GL)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(),
            ParamSpec(
                key="m",
                label="Lorentzian % (m), CasaXPS GL(m)",
                default=30.0,
                lower_default=0.0,
                upper_default=100.0,
                unit="%",
                ui={"step": 1.0, "min": 0.0, "max": 100.0},
            ),
        ],
    )


def _voigt_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="voigt",
        display_name="Voigt peak",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(key="fwhm_g", label="Gaussian FWHM"),
            _fwhm_param(key="fwhm_l", label="Lorentzian FWHM"),
        ],
    )


def _ds_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="ds",
        display_name="Doniach–Šunjić (DS)",
        params=[
            *_peak_pos_amp_params(),
            ParamSpec(
                key="gamma",
                label="Intrinsic width (γ)",
                default=5.0,
                lower_default=1e-6,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.1, "min": 0.0},
            ),
            ParamSpec(
                key="alpha",
                label="Asymmetry (α)",
                default=0.1,
                lower_default=0.0,
                upper_default=0.999,
                unit=None,
                ui={"step": 0.01, "min": 0.0, "max": 0.999},
            ),
        ],
    )


def _gds_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="gds",
        display_name="Gaussian-convoluted DS (GDS)",
        params=[
            *_peak_pos_amp_params(),
            ParamSpec(
                key="gamma",
                label="Intrinsic width (γ)",
                default=5.0,
                lower_default=1e-6,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.1, "min": 0.0},
            ),
            ParamSpec(
                key="alpha",
                label="Asymmetry (α)",
                default=0.1,
                lower_default=0.0,
                upper_default=0.999,
                unit=None,
                ui={"step": 0.01, "min": 0.0, "max": 0.999},
            ),
            ParamSpec(
                key="sigma",
                label="Gaussian σ (instrumental)",
                default=3.0,
                lower_default=0.0,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.1, "min": 0.0},
            ),
        ],
    )


def _la_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="la",
        display_name="Asymmetric Lorentzian (LA)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(default=10.0),
            ParamSpec(
                key="alpha",
                label="High-BE exponent (α)",
                default=1.5,
                lower_default=1e-3,
                upper_default=None,
                unit=None,
                ui={"step": 0.1, "min": 0.0},
            ),
            ParamSpec(
                key="beta",
                label="Low-BE exponent (β)",
                default=1.0,
                lower_default=1e-3,
                upper_default=None,
                unit=None,
                ui={"step": 0.1, "min": 0.0},
            ),
            ParamSpec(
                key="fwhm_g",
                label="Gaussian FWHM broadening",
                default=0.0,
                lower_default=0.0,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.1, "min": 0.0},
            ),
        ],
    )


def _lf_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="lf",
        display_name="Finite Lorentzian (LF)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(default=10.0),
            ParamSpec(
                key="alpha",
                label="High-BE exponent (α)",
                default=1.5,
                lower_default=1e-3,
                upper_default=None,
                unit=None,
                ui={"step": 0.1, "min": 0.0},
            ),
            ParamSpec(
                key="beta",
                label="Low-BE exponent (β)",
                default=1.0,
                lower_default=1e-3,
                upper_default=None,
                unit=None,
                ui={"step": 0.1, "min": 0.0},
            ),
            ParamSpec(
                key="w",
                label="Tail damping length (w)",
                default=20.0,
                lower_default=1e-6,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.5, "min": 0.0},
            ),
            ParamSpec(
                key="fwhm_g",
                label="Gaussian FWHM broadening",
                default=0.0,
                lower_default=0.0,
                upper_default=None,
                unit="cm^-1",
                ui={"step": 0.1, "min": 0.0},
            ),
        ],
    )


def _apv_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="apv",
        display_name="Asymmetric Gaussian–Lorentzian (APV)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(key="fwhm_l", label="Left FWHM", default=10.0),
            _fwhm_param(key="fwhm_r", label="Right FWHM", default=10.0),
            ParamSpec(
                key="eta_l",
                label="Left Lorentzian fraction (ηL)",
                default=0.5,
                lower_default=0.0,
                upper_default=1.0,
                unit=None,
                ui={"step": 0.01, "min": 0.0, "max": 1.0},
            ),
            ParamSpec(
                key="eta_r",
                label="Right Lorentzian fraction (ηR)",
                default=0.5,
                lower_default=0.0,
                upper_default=1.0,
                unit=None,
                ui={"step": 0.01, "min": 0.0, "max": 1.0},
            ),
        ],
    )


def _a_gl_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="a_gl",
        display_name="Asymmetric GL A(a,n,m)GL(m)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(default=1.0),
            ParamSpec(
                key="m",
                label="Lorentzian % (m), CasaXPS GL(m)",
                default=30.0,
                lower_default=0.0,
                upper_default=100.0,
                ui={"step": 1.0, "min": 0.0, "max": 100.0},
            ),
            ParamSpec(
                key="a",
                label="Asymmetry strength (a)",
                default=0.4,
                lower_default=0.0,
                upper_default=None,
                ui={"step": 0.05, "min": 0.0},
            ),
            ParamSpec(
                key="n",
                label="Asymmetry power (n)",
                default=0.55,
                lower_default=0.0,
                upper_default=None,
                ui={"step": 0.05, "min": 0.0},
            ),
            ParamSpec(
                key="m_asym",
                label="Asymmetry Gaussian index (m)",
                default=10.0,
                lower_default=0.0,
                upper_default=None,
                ui={"step": 1.0, "min": 0.0},
            ),
        ],
    )


def _asymmetric_voigt_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="asymmetric_voigt",
        display_name="Asymmetric Voigt (split)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(key="fwhm_g_l", label="Left Gaussian FWHM", default=8.0),
            _fwhm_param(key="fwhm_l_l", label="Left Lorentzian FWHM", default=6.0),
            _fwhm_param(key="fwhm_g_r", label="Right Gaussian FWHM", default=8.0),
            _fwhm_param(key="fwhm_l_r", label="Right Lorentzian FWHM", default=6.0),
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


def _shirley_bg_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="shirley_bg",
        display_name="Shirley background (active)",
        params=[
            ParamSpec(key="k", label="Shirley k", default=0.03, lower_default=0.0, upper_default=None, ui={"step": 0.001}),
            ParamSpec(key="const", label="Constant", default=0.0, lower_default=None, upper_default=None, ui={"step": 1.0}),
        ],
    )


def _tougaard_bg_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="tougaard_bg",
        display_name="Tougaard background (active)",
        params=[
            ParamSpec(key="B", label="B", default=2866.0, lower_default=0.0, upper_default=None, ui={"step": 1.0}),
            ParamSpec(key="C", label="C", default=1643.0, lower_default=0.0, upper_default=None, ui={"step": 1.0}),
            ParamSpec(key="C_d", label="C'", default=1.0, lower_default=0.0, upper_default=None, ui={"step": 0.1}),
            ParamSpec(key="D", label="D", default=1.0, lower_default=0.0, upper_default=None, ui={"step": 0.1}),
            ParamSpec(key="extend", label="Extend (eV)", default=0.0, lower_default=0.0, upper_default=None, ui={"step": 1.0}),
        ],
    )


def _slope_bg_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="slope_bg",
        display_name="Slope background (active)",
        params=[
            ParamSpec(key="k", label="Slope k", default=0.001, lower_default=0.0, upper_default=None, ui={"step": 0.0001}),
        ],
    )


def _fermi_edge_spec() -> ComponentSpec:
    """
    lmfitxps FermiEdgeModel (Gaussian ⊗ Fermi–Dirac).

    ``temperature_K`` is shown to the user; the fit engine converts to kt = kB·T.
    Amplitude defaults to auto (engine estimates step height when initial amp ≤ 0).
    """
    return ComponentSpec(
        component_type="fermi_edge",
        display_name="Fermi edge (valence)",
        params=[
            ParamSpec(
                key="amplitude",
                label="Amplitude",
                default=0.0,
                lower_default=0.0,
                upper_default=1.0e7,
                ui={"step": 1.0, "auto_default": True, "auto_sentinel": True},
            ),
            ParamSpec(
                key="center",
                label="Center (Ef)",
                default=0.0,
                lower_default=-3.0,
                upper_default=3.0,
                unit="eV",
                ui={"step": 0.01},
            ),
            ParamSpec(
                key="sigma",
                label="Sigma",
                default=0.25,
                lower_default=0.05,
                upper_default=0.4,
                unit="eV",
                ui={"step": 0.01},
            ),
            ParamSpec(
                key="temperature_K",
                label="Temperature",
                default=298.0,
                lower_default=None,
                upper_default=None,
                unit="K",
                ui={"step": 1.0, "vary_default": False, "bounds_editable": False},
            ),
        ],
    )


def list_component_types() -> list[ComponentSpec]:
    # Parameterized specs (like polynomial degree) are represented via templates.
    # For the UI catalog we include a few common degrees.
    base = [
        _gaussian_spec(),
        _lorentzian_spec(),
        _pseudo_voigt_spec(),
        _gl_spec(),
        _voigt_spec(),
        _ds_spec(),
        _gds_spec(),
        _la_spec(),
        _lf_spec(),
        _a_gl_spec(),
        _apv_spec(),
        _asymmetric_voigt_spec(),
    ]
    base.extend(polynomial_background_spec(d) for d in (0, 1, 2, 3, 4))
    base.extend([_shirley_bg_spec(), _tougaard_bg_spec(), _slope_bg_spec(), _fermi_edge_spec()])
    return base


_BUILDERS: dict[str, Callable[[], tuple[Callable[..., np.ndarray], list[ParamSpec]]]] = {
    "gaussian": lambda: (fitting_models.gaussian, _gaussian_spec().params),
    "lorentzian": lambda: (fitting_models.lorentzian, _lorentzian_spec().params),
    "pseudo_voigt": lambda: (fitting_models.pseudo_voigt, _pseudo_voigt_spec().params),
    "gl": lambda: (fitting_models.gl, _gl_spec().params),
    "voigt": lambda: (fitting_models.voigt, _voigt_spec().params),
    "ds": lambda: (fitting_models.ds, _ds_spec().params),
    "gds": lambda: (fitting_models.gds, _gds_spec().params),
    "la": lambda: (fitting_models.la, _la_spec().params),
    "lf": lambda: (fitting_models.lf, _lf_spec().params),
    "a_gl": lambda: (fitting_models.a_gl, _a_gl_spec().params),
    "apv": lambda: (fitting_models.apv, _apv_spec().params),
    "asymmetric_voigt": lambda: (fitting_models.asymmetric_voigt, _asymmetric_voigt_spec().params),
}


def component_param_specs(component_type: str, degree: int | None = None) -> list[ParamSpec]:
    """Ordered ParamSpecs for a component type (including XPS backgrounds)."""
    ct = component_type.strip().lower()
    if ct == "polynomial_background":
        if degree is None:
            raise ValueError("degree is required for polynomial_background")
        return list(polynomial_background_spec(int(degree)).params)
    if ct == "shirley_bg":
        return list(_shirley_bg_spec().params)
    if ct == "tougaard_bg":
        return list(_tougaard_bg_spec().params)
    if ct == "slope_bg":
        return list(_slope_bg_spec().params)
    if ct == "fermi_edge":
        return list(_fermi_edge_spec().params)
    _fn, params = build_component_function(ct, degree=degree)
    return list(params)


def build_component_function(component_type: str, degree: int | None = None) -> tuple[Callable[..., np.ndarray], list[ParamSpec]]:
    """
    Return a callable f(x, *params) and the corresponding ordered ParamSpecs.
    """
    ct = component_type.strip().lower()
    if ct == "polynomial_background":
        if degree is None:
            raise ValueError("degree is required for polynomial_background")
        spec = polynomial_background_spec(int(degree))
        return fitting_models.polynomial_background, spec.params
    if ct in XPS_LMFITXPS_COMPONENT_TYPES:
        # Active XPS backgrounds / Fermi edge are only evaluable via lmfitxps (see fitting_lmfit).
        raise ValueError(
            f"component_type {component_type!r} requires the XPS/lmfit fitting path "
            "(lmfitxps model); it cannot be used with curve_fit"
        )
    builder = _BUILDERS.get(ct)
    if builder is None:
        raise ValueError(f"Unknown component_type: {component_type}")
    return builder()
