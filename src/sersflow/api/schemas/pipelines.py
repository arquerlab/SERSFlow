from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from sersflow.api.schemas.pipeline import Pipeline


class PipelineLibraryItem(BaseModel):
    pipeline_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pipeline: Pipeline
    created_at: str
    updated_at: str


class PipelineCreateRequest(BaseModel):
    name: str = Field(max_length=200)
    pipeline: Pipeline = Field(default_factory=Pipeline)

    @field_validator("name")
    @classmethod
    def name_nonempty_stripped(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("name is required")
        return s


class PipelineCreateResponse(BaseModel):
    item: PipelineLibraryItem


class PipelineListResponse(BaseModel):
    items: list[PipelineLibraryItem] = Field(default_factory=list)
    count: int = Field(ge=0)


class PipelineGetResponse(BaseModel):
    item: PipelineLibraryItem
