from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sersflow.api.schemas.datasets import SpectrumRef

InputFrom = Literal["previous", "initial", "after_step"]


class PipelineStep(BaseModel):
    name: str = Field(min_length=1)
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Step-specific parameters. For normalize: method may be max, min, mean, median, vector/l2, "
            "spectrum_point with point_x, baseline_point with baseline_step_id and point_x, or legacy "
            "baseline with baseline_point for spectrum-point normalization."
        ),
    )
    enabled: bool = True
    impl_version: str | None = None
    step_id: str | None = None
    input_from: InputFrom = "previous"
    after_step_id: str | None = None

    @model_validator(mode="after")
    def validate_after_step(self) -> PipelineStep:
        if self.input_from == "after_step":
            aid = (self.after_step_id or "").strip()
            if not aid:
                raise ValueError("after_step_id is required when input_from is 'after_step'")
            self.after_step_id = aid
        else:
            self.after_step_id = None
        return self


class Pipeline(BaseModel):
    steps: list[PipelineStep] = Field(default_factory=list)


class ReturnMetricsOnly(BaseModel):
    kind: Literal["metrics_only"] = "metrics_only"
    metrics: list[str] = Field(default_factory=list)


class ReturnFinal(BaseModel):
    kind: Literal["final"] = "final"


PipelineReturnSpec = ReturnMetricsOnly | ReturnFinal


class PipelineRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    inputs: list[SpectrumRef] = Field(min_length=1)
    pipeline: Pipeline = Field(default_factory=Pipeline)
    return_: PipelineReturnSpec = Field(default_factory=ReturnMetricsOnly, alias="return")
    up_to_step: str | None = None
    cache_namespace: str | None = None


class MetricValue(BaseModel):
    name: str
    value: float | None = None
    unit: str | None = None


class SpectrumMetrics(BaseModel):
    spectrum_id: str
    metrics: list[MetricValue] = Field(default_factory=list)


class PipelineRunMetricsResponse(BaseModel):
    items: list[SpectrumMetrics] = Field(default_factory=list)


class SpectrumSeries(BaseModel):
    spectrum_id: str
    x: list[float]
    y: list[float]


class PipelineRunFinalResponse(BaseModel):
    items: list[SpectrumSeries] = Field(default_factory=list)


class SweepSpec(BaseModel):
    step: str = Field(min_length=1)
    grid: dict[str, list[Any]] = Field(default_factory=dict)


class SweepObjective(BaseModel):
    metric: str = Field(min_length=1)
    aggregate: Literal["mean", "median"] = "median"


class PipelineSweepRequest(BaseModel):
    inputs: list[SpectrumRef] = Field(min_length=1)
    base_pipeline: Pipeline = Field(default_factory=Pipeline)
    sweep: SweepSpec
    objective: SweepObjective
    cache_namespace: str | None = None


class SweepResult(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    objective: float | None = None


class PipelineSweepResponse(BaseModel):
    results: list[SweepResult] = Field(default_factory=list)
    best: SweepResult | None = None

