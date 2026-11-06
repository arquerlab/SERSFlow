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
        "sgl",
        "gl_gauss",
        "voigt",
        "ds",
        "gds",
        "la",
        "lf",
        "a_gl",
        "a_sgl",
        "apv",
        "asymmetric_voigt",
    }
)

# Ideal DS / GDS tails are non-integrable for alpha > 0: their area is integrated over the fit window (L1, user
# decision), so they export areas too. Kept for callers that need to know the area is window-dependent.
INFINITE_AREA_COMPONENT_TYPES = frozenset({"ds", "gds"})
WINDOW_AREA_COMPONENT_TYPES = INFINITE_AREA_COMPONENT_TYPES

# Measured reference spectrum (M1): normalised to unit area, so its amplitude is its area.
REFERENCE_COMPONENT_TYPES = frozenset({"reference_spectrum"})

# Peaks that export a derived area column (analytical or numeric).
AREA_EXPORT_COMPONENT_TYPES = PEAK_COMPONENT_TYPES | REFERENCE_COMPONENT_TYPES

# x-only background callables (B1): fitted with the peaks, evaluable by both engines.
CALLABLE_BACKGROUND_TYPES = frozenset({"erfc_step_bg", "linear_bg"})

# Components whose function depends on component options (``of`` peak, ``reference_id``): XPS / lmfit only.
OPTION_COMPONENT_TYPES = frozenset({"shirley_of_bg", "reference_spectrum"})

XPS_BACKGROUND_COMPONENT_TYPES = frozenset({"shirley_bg", "tougaard_bg", "slope_bg", "tougaard_u4_bg"})

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
            # Auto initial guess (≤0 sentinel) on by default; user can override per peak.
            ui={"step": 1.0, "auto_default": True, "auto_sentinel": True},
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


def _gl_m_param(label: str = "Lorentzian % (m), CasaXPS GL(m)") -> ParamSpec:
    return ParamSpec(
        key="m",
        label=label,
        default=30.0,
        lower_default=0.0,
        upper_default=100.0,
        unit="%",
        ui={"step": 1.0, "min": 0.0, "max": 100.0},
    )


def _gl_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="gl",
        display_name="GL(m) Gaussian×Lorentzian product (CasaXPS)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(label="FWHM (true)"),
            _gl_m_param(),
        ],
    )


def _sgl_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="sgl",
        display_name="SGL(m) Gaussian+Lorentzian sum (CasaXPS SGL)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(),
            _gl_m_param("Lorentzian % (m), CasaXPS SGL(m)"),
        ],
    )


def _gl_gauss_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="gl_gauss",
        display_name="GL(m,n) product GL convolved with Gaussian (CasaXPS)",
        params=[
            *_peak_pos_amp_params(),
            _fwhm_param(label="FWHM of GL(m) core (true)"),
            _gl_m_param(),
            ParamSpec(
                key="fwhm_g",
                label="Gaussian FWHM n (convolution)",
                default=0.3,
                lower_default=0.0,
                upper_default=None,
                ui={"step": 0.05, "min": 0.0},
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
                label="w (tail damping width, eV)",
                default=100.0,
                lower_default=1e-6,
                upper_default=None,
                unit="eV",
                ui={"step": 0.5, "min": 0.0},
            ),
            ParamSpec(
                key="fwhm_g",
                label="Gaussian FWHM (eV; not the CasaXPS m index)",
                default=0.0,
                lower_default=0.0,
                upper_default=None,
                unit="eV",
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


def _a_gl_spec(component_type: str = "a_gl") -> ComponentSpec:
    display = (
        "Asymmetric GL A(a,n,m)GL(m) (product base)"
        if component_type == "a_gl"
        else "Asymmetric SGL A(a,n,m)SGL(m) (legacy sum base)"
    )
    return ComponentSpec(
        component_type=component_type,
        display_name=display,
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


def _erfc_step_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="erfc_step_bg",
        display_name="erfc step / edge (active)",
        params=[
            ParamSpec(key="pos", label="Step position (inflection)", default=0.0, lower_default=None, upper_default=None, unit="eV", ui={"step": 0.01}),
            ParamSpec(key="height", label="Step height", default=0.0, lower_default=None, upper_default=None, ui={"step": 1.0}),
            ParamSpec(key="fwhm", label="Edge FWHM", default=0.5, lower_default=1e-3, upper_default=None, unit="eV", ui={"step": 0.01}),
            ParamSpec(key="const", label="Low level", default=0.0, lower_default=None, upper_default=None, ui={"step": 1.0}),
        ],
    )


def _linear_bg_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="linear_bg",
        display_name="Linear background (endpoints)",
        params=[
            ParamSpec(key="low", label="Value at low-x end", default=0.0, lower_default=None, upper_default=None, ui={"step": 1.0, "vary_default": False}),
            ParamSpec(key="high", label="Value at high-x end", default=0.0, lower_default=None, upper_default=None, ui={"step": 1.0, "vary_default": False}),
        ],
    )


def _tougaard_u4_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="tougaard_u4_bg",
        display_name="Tougaard U2/U3/U4 (active, with T0)",
        params=[
            ParamSpec(key="B", label="B", default=2866.0, lower_default=0.0, upper_default=None, unit="eV^2", ui={"step": 10.0}),
            ParamSpec(key="C", label="C", default=1643.0, lower_default=None, upper_default=None, unit="eV^2", ui={"step": 1.0, "vary_default": False}),
            ParamSpec(key="C_d", label="C' (sign: +1 U2, -1 U3/U4)", default=1.0, lower_default=None, upper_default=None, ui={"step": 1.0, "vary_default": False}),
            ParamSpec(key="D", label="D", default=0.0, lower_default=0.0, upper_default=None, unit="eV^2", ui={"step": 1.0, "vary_default": False}),
            ParamSpec(key="T0", label="T0 (onset / band gap)", default=0.0, lower_default=0.0, upper_default=None, unit="eV", ui={"step": 0.1, "vary_default": False}),
        ],
    )


def _shirley_of_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="shirley_of_bg",
        display_name="Shirley of a peak (SB, active)",
        params=[
            ParamSpec(key="k", label="Shirley k", default=0.01, lower_default=0.0, upper_default=None, ui={"step": 0.001}),
            ParamSpec(key="shift", label="Energy shift", default=0.0, lower_default=-5.0, upper_default=5.0, unit="eV", ui={"step": 0.05, "vary_default": False}),
        ],
    )


def _reference_spec() -> ComponentSpec:
    return ComponentSpec(
        component_type="reference_spectrum",
        display_name="Reference spectrum (measured)",
        params=[
            ParamSpec(key="amp", label="Area (scale)", default=1.0, lower_default=0.0, upper_default=None, ui={"step": 1.0}),
            ParamSpec(key="shift", label="Energy shift", default=0.0, lower_default=-1.0, upper_default=1.0, unit="eV", ui={"step": 0.01, "vary_default": False}),
        ],
    )


def _fermi_edge_spec() -> ComponentSpec:
    """
    lmfitxps FermiEdgeModel (Gaussian-broadened Fermi-Dirac) plus a constant intensity floor.

    ``temperature_K`` is shown to the user; the fit engine converts to kt = kB*T.
    Amplitude and ``const`` default to auto (engine estimates step height / floor when
    initial values are <= 0). ``const`` is required when intensity below Ef does not
    drop to zero.
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
            ParamSpec(
                key="const",
                label="Const (floor)",
                default=0.0,
                lower_default=0.0,
                upper_default=1.0e7,
                ui={"step": 1.0, "auto_default": True, "auto_sentinel": True},
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
        _sgl_spec(),
        _gl_gauss_spec(),
        _voigt_spec(),
        _ds_spec(),
        _gds_spec(),
        _la_spec(),
        _lf_spec(),
        _a_gl_spec(),
        _a_gl_spec("a_sgl"),
        _apv_spec(),
        _asymmetric_voigt_spec(),
    ]
    base.extend(polynomial_background_spec(d) for d in (0, 1, 2, 3, 4))
    base.extend([_shirley_bg_spec(), _tougaard_bg_spec(), _slope_bg_spec(), _fermi_edge_spec()])
    base.extend([_erfc_step_spec(), _linear_bg_spec(), _tougaard_u4_spec(), _shirley_of_spec(), _reference_spec()])
    return base


_BUILDERS: dict[str, Callable[[], tuple[Callable[..., np.ndarray], list[ParamSpec]]]] = {
    "gaussian": lambda: (fitting_models.gaussian, _gaussian_spec().params),
    "lorentzian": lambda: (fitting_models.lorentzian, _lorentzian_spec().params),
    "pseudo_voigt": lambda: (fitting_models.pseudo_voigt, _pseudo_voigt_spec().params),
    "gl": lambda: (fitting_models.gl, _gl_spec().params),
    "sgl": lambda: (fitting_models.sgl, _sgl_spec().params),
    "gl_gauss": lambda: (fitting_models.gl_gauss, _gl_gauss_spec().params),
    "voigt": lambda: (fitting_models.voigt, _voigt_spec().params),
    "ds": lambda: (fitting_models.ds, _ds_spec().params),
    "gds": lambda: (fitting_models.gds, _gds_spec().params),
    "la": lambda: (fitting_models.la, _la_spec().params),
    "lf": lambda: (fitting_models.lf, _lf_spec().params),
    "a_gl": lambda: (fitting_models.a_gl, _a_gl_spec().params),
    "a_sgl": lambda: (fitting_models.a_sgl, _a_gl_spec("a_sgl").params),
    "apv": lambda: (fitting_models.apv, _apv_spec().params),
    "asymmetric_voigt": lambda: (fitting_models.asymmetric_voigt, _asymmetric_voigt_spec().params),
    "erfc_step_bg": lambda: (_xc().erfc_step_bg, _erfc_step_spec().params),
    "linear_bg": lambda: (_xc().linear_bg, _linear_bg_spec().params),
}


def _xc():
    from sersflow.core.preprocess import xps_extra_components

    return xps_extra_components


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
    if ct == "tougaard_u4_bg":
        return list(_tougaard_u4_spec().params)
    if ct == "shirley_of_bg":
        return list(_shirley_of_spec().params)
    if ct == "reference_spectrum":
        return list(_reference_spec().params)
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
    if ct in OPTION_COMPONENT_TYPES:
        raise ValueError(
            f"component_type {component_type!r} depends on component options (peak / reference id); "
            "build it with build_component_function_for"
        )
    builder = _BUILDERS.get(ct)
    if builder is None:
        raise ValueError(f"Unknown component_type: {component_type}")
    return builder()


def build_component_function_for(
    component_type: str,
    *,
    degree: int | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[Callable[..., np.ndarray], list[ParamSpec]]:
    """``build_component_function`` plus option-dependent types (``reference_spectrum``)."""
    ct = component_type.strip().lower()
    if ct == "reference_spectrum":
        from sersflow.core.preprocess.reference_component import make_reference_function

        return make_reference_function(options or {}), list(_reference_spec().params)
    return build_component_function(ct, degree=degree)
