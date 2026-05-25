from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from sersflow.api.schemas.pipeline import Pipeline


class PipelineLibraryItem(BaseModel):
    pipeline_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pipeline: Pipeline
    created_at: str
    updated_at: str


class PipelineCreateRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    pipeline: Pipeline = Field(default_factory=Pipeline)

    @field_validator("name")
    @classmethod
    def name_stripped(cls, v: str) -> str:
        return (v or "").strip()


class PipelineCreateResponse(BaseModel):
    item: PipelineLibraryItem


class PipelineListResponse(BaseModel):
    items: list[PipelineLibraryItem] = Field(default_factory=list)
    count: int = Field(ge=0)


class PipelineGetResponse(BaseModel):
    item: PipelineLibraryItem


class PipelineUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    pipeline: Pipeline | None = None

    @field_validator("name")
    @classmethod
    def name_optional_stripped(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = (v or "").strip()
        if not s:
            raise ValueError("name cannot be empty when provided")
        return s

    @model_validator(mode="after")
    def at_least_one_field(self) -> PipelineUpdateRequest:
        if self.name is None and self.pipeline is None:
            raise ValueError("At least one of name or pipeline is required")
        return self


class PipelineUpdateResponse(BaseModel):
    item: PipelineLibraryItem


class PipelineExportPackage(BaseModel):
    schema_version: str = "sersflow.pipeline.v1"
    created_by: str = "SERSFlow"
    exported_at: str
    name: str
    pipeline: Pipeline
    source_pipeline_id: str | None = None


class PipelineImportRequest(BaseModel):
    schema_version: str = "sersflow.pipeline.v1"
    name: str | None = Field(default=None, max_length=200)
    pipeline: Pipeline

    @field_validator("name")
    @classmethod
    def import_name_optional_stripped(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = (v or "").strip()
        return s or None


class PipelineImportResponse(BaseModel):
    item: PipelineLibraryItem
