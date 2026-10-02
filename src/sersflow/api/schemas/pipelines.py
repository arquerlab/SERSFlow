from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from sersflow.api.schemas.pipeline import Pipeline, TechniqueFamily


class PipelineLibraryItem(BaseModel):
    pipeline_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pipeline: Pipeline
    technique_family: TechniqueFamily = "vibrational"
    created_at: str
    updated_at: str


class PipelineCreateRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    pipeline: Pipeline = Field(default_factory=Pipeline)
    technique_family: TechniqueFamily | None = None

    @field_validator("name")
    @classmethod
    def name_stripped(cls, v: str) -> str:
        return (v or "").strip()

    @model_validator(mode="after")
    def resolve_technique_family(self) -> PipelineCreateRequest:
        fam = self.technique_family or self.pipeline.technique_family
        if fam not in ("vibrational", "xps"):
            raise ValueError("technique_family is required (vibrational or xps)")
        self.technique_family = fam
        self.pipeline = self.pipeline.model_copy(update={"technique_family": fam})
        return self


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
    technique_family: TechniqueFamily | None = None

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
        if self.name is None and self.pipeline is None and self.technique_family is None:
            raise ValueError("At least one of name, pipeline, or technique_family is required")
        return self


class PipelineUpdateResponse(BaseModel):
    item: PipelineLibraryItem


class PipelineExportPackage(BaseModel):
    schema_version: str = "sersflow.pipeline.v1"
    created_by: str = "SpecFlow"
    exported_at: str
    name: str
    pipeline: Pipeline
    technique_family: TechniqueFamily = "vibrational"
    source_pipeline_id: str | None = None


class PipelineImportRequest(BaseModel):
    schema_version: str = "sersflow.pipeline.v1"
    name: str | None = Field(default=None, max_length=200)
    pipeline: Pipeline
    technique_family: TechniqueFamily | None = None

    @field_validator("name")
    @classmethod
    def import_name_optional_stripped(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = (v or "").strip()
        return s or None

    @model_validator(mode="after")
    def resolve_technique_family(self) -> PipelineImportRequest:
        fam = self.technique_family or getattr(self.pipeline, "technique_family", None) or "vibrational"
        self.technique_family = fam  # type: ignore[assignment]
        self.pipeline = self.pipeline.model_copy(update={"technique_family": fam})
        return self


class PipelineImportResponse(BaseModel):
    item: PipelineLibraryItem
