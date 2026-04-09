from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sersflow.api.schemas.datasets import SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline


class MetricValue(BaseModel):
    name: str
    value: float | None = None
    unit: str | None = None


class SpectrumMetrics(BaseModel):
    spectrum_id: str
    metrics: list[MetricValue] = Field(default_factory=list)


class MetricsRow(BaseModel):
    spectrum_id: str
    values: list[float | None] = Field(default_factory=list)


class MetricsComputeRequest(BaseModel):
    inputs: list[SpectrumRef] = Field(min_length=1)
    metrics: list[str] = Field(min_length=1)
    pipeline: Pipeline | None = None
    cache_namespace: str | None = None


class MetricsComputeResponse(BaseModel):
    items: list[SpectrumMetrics] = Field(default_factory=list)


class DatasetMetricsRequest(BaseModel):
    metrics: list[str] = Field(min_length=1)
    pipeline: Pipeline | None = None
    scope: dict[str, Any] | None = None
    cache_namespace: str | None = None
    format: str = "columnar"


class DatasetMetricsResponse(BaseModel):
    metric_names: list[str] = Field(default_factory=list)
    rows: list[MetricsRow] = Field(default_factory=list)

