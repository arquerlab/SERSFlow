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

    @model_validator(mode="after")
    def validate_lengths(self) -> "FitInlineSeries":
        if len(self.x) != len(self.y):
            raise ValueError("x and y length mismatch")
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
    auto: for each Gaussian, set initial amplitude to the spectrum y value at the initial center (pos).
    """


class FitComponentResult(BaseModel):
    component_id: str
    component_type: str
    degree: int | None = None
    param_keys: list[str] = Field(default_factory=list)
    params: dict[str, float] = Field(default_factory=dict)
    y_hat: list[float] | None = None
    """This component's contribution on the same x as the request (same length as target)."""


class FitResponse(BaseModel):
    params_vector: list[float] = Field(default_factory=list)
    components: list[FitComponentResult] = Field(default_factory=list)
    y_hat: list[float] | None = None
    """Total fitted curve (sum of components)."""

