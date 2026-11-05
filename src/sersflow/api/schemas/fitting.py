from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from sersflow.api.schemas.datasets import SpectrumRef


class ParamBoundsDefault(BaseModel):
    lower: float | None = None
    upper: float | None = None


class ParamSpecPublic(BaseModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    default: float | None = None
    bounds_default: ParamBoundsDefault = Field(default_factory=ParamBoundsDefault)
    unit: str | None = None
    ui: dict[str, Any] = Field(default_factory=dict)


class ComponentSpecPublic(BaseModel):
    component_type: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    kind: Literal["fixed", "parametric"] = "fixed"
    params: list[ParamSpecPublic] = Field(default_factory=list)


class FittingModelsResponse(BaseModel):
    components: list[ComponentSpecPublic] = Field(default_factory=list)


class FitInlineSeries(BaseModel):
    kind: Literal["inline"] = "inline"
    x: list[float] = Field(min_length=3)
    y: list[float] = Field(min_length=3)
    y_variance: list[float] | None = None
    """Counting variance of y (e.g. ``var`` from /pipeline/run final); enables Poisson weighting (F1)."""
    variance_kind: Literal["absolute", "relative"] | None = None

    @model_validator(mode="after")
    def validate_lengths(self) -> "FitInlineSeries":
        if len(self.x) != len(self.y):
            raise ValueError("x and y length mismatch")
        if self.y_variance is not None and len(self.y_variance) != len(self.y):
            raise ValueError("y_variance and y length mismatch")
        return self


class FitSpectrumRef(BaseModel):
    kind: Literal["spectrum_ref"] = "spectrum_ref"
    spectrum: SpectrumRef


FitTarget = FitInlineSeries | FitSpectrumRef


class FitComponentRequest(BaseModel):
    component_id: str = Field(min_length=1)
    component_type: str = Field(min_length=1)
    degree: int | None = None


class FitBounds(BaseModel):
    lower: list[float | None] = Field(default_factory=list)
    upper: list[float | None] = Field(default_factory=list)


class FitRequest(BaseModel):
    target: FitTarget
    components: list[FitComponentRequest] = Field(min_length=1)
    p0: list[float] = Field(default_factory=list)
    bounds: FitBounds = Field(default_factory=FitBounds)
    return_curve: bool = True
    initial_guess_mode: Literal["default", "auto"] = "default"
    """
    default: use p0 from the client for all parameters.
    auto: for each peak (gaussian / lorentzian / pseudo_voigt / gl / voigt /
    ds / gds / la / lf / apv / asymmetric_voigt), set initial amplitude to the
    spectrum y value at the initial center (pos).
    """
    technique_family: Literal["vibrational", "xps", "xas"] = "vibrational"
    vary: list[bool] | None = None
    param_links: list[dict[str, Any]] | None = None
    xps_region: str | None = None
    fit_min_x: float | None = None
    """Optional internal fit window lower bound (inclusive)."""
    fit_max_x: float | None = None
    """Optional internal fit window upper bound (inclusive)."""
    initial_area_ratios: str | None = None
    """Optional Area1:Area2:... string for chord-based amplitude auto-guess."""
    weighting: Literal["auto", "poisson", "poisson_relative", "none"] | None = None
    """F1: auto (default; Poisson for XPS when counting variance is known), poisson, poisson_relative, none."""


class FitComponentResult(BaseModel):
    component_id: str
    component_type: str
    degree: int | None = None
    param_keys: list[str] = Field(default_factory=list)
    params: dict[str, float] = Field(default_factory=dict)
    y_hat: list[float] | None = None
    """This component's contribution on the same x as the request (same length as target)."""
    stderr: dict[str, float | None] = Field(default_factory=dict)
    """F2: 1-sigma covariance error per parameter (null for fixed parameters or when unavailable)."""
    area: float | None = None
    area_stderr: float | None = None
    area_pct: float | None = None
    """Share of the summed peak areas of this fit, in % (backgrounds excluded)."""
    area_pct_stderr: float | None = None


class FitDiagnosticsPublic(BaseModel):
    rmse: float | None = None
    r2: float | None = None
    r2_adj: float | None = None
    ssr: float | None = None
    aic: float | None = None
    bic: float | None = None
    aicc: float | None = None
    chi2: float | None = None
    redchi: float | None = None
    resid_mad: float | None = None
    max_abs_resid: float | None = None
    success: float | None = None
    n_points: float | None = None
    n_vary: float | None = None
    nfev: float | None = None
    median_rel_stderr: float | None = None
    n_at_bound: float | None = None
    """Free parameters sitting on a bound (the model is asking for more freedom than it has)."""
    bg_gt_data_frac: float | None = None
    """Fraction of points where the fitted background is above the data."""
    resid_mean_edge_lo: float | None = None
    resid_mean_edge_hi: float | None = None
    """Mean residual (data - fit) over the outermost ~5% of the window at the low-/high-x end."""
    resid_lag1_autocorr: float | None = None
    """Lag-1 autocorrelation of the residual (0 = noise-like, near 1 = structured)."""
    weighting: str | None = None
    """Weighting applied: poisson | poisson_relative | none (F1)."""
    weighting_note: str | None = None
    residual_std_normalised: float | None = None
    """STD of residual / sigma: ≈1 when the misfit is at counting-noise level (relative Poisson: ≈1 by construction)."""
    chi2_reduced_weighted: float | None = None
    """Weighted reduced chi2 (absolute Poisson only)."""
    poisson_gain: float | None = None
    """Relative Poisson: fitted gain g in var = g*y (data units per count); 1 for raw counts."""


class ValidateLinksRequest(BaseModel):
    """F4: check a fitting step's ``param_links`` (expressions, cycles, unknown names) without fitting."""

    components: list[dict[str, Any]] = Field(description="[{component_id, component_type, degree?}, ...]")
    param_links: list[dict[str, Any]] = Field(default_factory=list)


class ValidateLinksResponse(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    drivers: dict[str, list[str]] = Field(default_factory=dict)
    """``"<component>.<key>"`` -> component ids it follows (for colour-coding linked fields)."""


class FitResponse(BaseModel):
    params_vector: list[float] = Field(default_factory=list)
    components: list[FitComponentResult] = Field(default_factory=list)
    y_hat: list[float] | None = None
    """Total fitted curve (sum of components)."""
    residual: list[float] | None = None
    """y - y_hat when return_curve; not persisted."""
    residual_normalised: list[float | None] | None = None
    """(y - y_hat) / sigma when the fit was weighted (F1); null otherwise."""
    diagnostics: FitDiagnosticsPublic | None = None
