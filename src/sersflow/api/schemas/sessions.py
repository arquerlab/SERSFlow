from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sersflow.api.schemas.pipeline import Pipeline


class SubsetStrategy(BaseModel):
    kind: Literal["all", "indices", "random", "top_n", "outliers"] = "all"
    indices: list[int] | None = None
    seed: int | None = None
    n: int | None = None
    metric: str | None = None
    direction: Literal["max", "min"] | None = None
    zscore_threshold: float | None = None


class SessionCacheInfo(BaseModel):
    cache_namespace: str = Field(min_length=1)
    pipeline_hash: str | None = None
    subset_hash: str | None = None


class Session(BaseModel):
    session_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    pipeline: Pipeline = Field(default_factory=Pipeline)
    subset: SubsetStrategy = Field(default_factory=SubsetStrategy)
    cache: SessionCacheInfo | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SessionCreateRequest(BaseModel):
    dataset_id: str = Field(min_length=1)
    pipeline: Pipeline | None = None
    subset: SubsetStrategy | None = None


class SessionCreateResponse(BaseModel):
    session: Session


class SessionGetResponse(BaseModel):
    session: Session


class SessionListItem(BaseModel):
    session_id: str
    dataset_id: str
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    items: list[SessionListItem]
    count: int


class SessionPipelineUpdateRequest(BaseModel):
    pipeline: Pipeline


class SessionPipelineUpdateResponse(BaseModel):
    pipeline: Pipeline
    pipeline_hash: str


class SessionSubsetUpdateResponse(BaseModel):
    subset: SubsetStrategy
    resolved: dict[str, Any]
    subset_hash: str


class SessionRunReturnMetricsOnly(BaseModel):
    kind: Literal["metrics_only"] = "metrics_only"
    metrics: list[str] = Field(min_length=1)


class SessionRunReturnFinal(BaseModel):
    kind: Literal["final"] = "final"


class SessionRunReturnIntermediates(BaseModel):
    kind: Literal["intermediates"] = "intermediates"
    steps: list[str] = Field(min_length=1)


SessionRunReturnSpec = SessionRunReturnMetricsOnly | SessionRunReturnFinal | SessionRunReturnIntermediates


class SessionRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope: Literal["subset", "all"] = "subset"
    return_: SessionRunReturnSpec = Field(alias="return")
    up_to_step: str | None = None

