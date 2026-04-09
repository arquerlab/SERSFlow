from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DatasetMetadata(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: str | None = None


class SpectrumRef(BaseModel):
    spectrum_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    source: str = "io_upload"
    record_index: int | None = None


class Dataset(BaseModel):
    dataset_id: str = Field(min_length=1)
    spectra: list[SpectrumRef] = Field(default_factory=list)
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)


class DatasetCreateRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)


class DatasetCreateResponse(BaseModel):
    dataset: Dataset


class DatasetListItem(BaseModel):
    dataset_id: str = Field(min_length=1)
    count: int = Field(ge=0)
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)


class DatasetListResponse(BaseModel):
    items: list[DatasetListItem] = Field(default_factory=list)
    count: int = Field(ge=0)


class DatasetGetResponse(BaseModel):
    dataset: Dataset


class DatasetMetricsRequest(BaseModel):
    # placeholder for later stages; keep contract stable
    metrics: list[str] = Field(default_factory=list)
    pipeline: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None

