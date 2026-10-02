from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

TechniqueFamily = Literal["vibrational", "xps"]


class DatasetMetadata(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: str | None = None
    """Technique family for this dataset. Missing/legacy datasets default to vibrational."""
    technique_family: TechniqueFamily = "vibrational"
    """Union of format capability tokens from source uploads (e.g. multi_block, xps_regions)."""
    capabilities: list[str] = Field(default_factory=list)


class SpectrumRef(BaseModel):
    spectrum_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    source: str = "io_upload"
    record_index: int | None = None
    blob_id: str | None = None
    blob_relative_path: str | None = None
    original_relative_path: str | None = None


class Dataset(BaseModel):
    dataset_id: str = Field(min_length=1)
    spectra: list[SpectrumRef] = Field(default_factory=list)
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)


class DatasetCreateRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)
    """
    When creating from VAMAS (.vms) uploads that contain both averaged and individual
    blocks: ``averages`` keeps only averages; ``individuals`` keeps only replicates;
    ``all`` keeps every block. Ignored for non-VMS files and for VMS files that only
    contain one role (except ``all``, which always keeps all blocks).
    """
    vms_spectrum_mode: Literal["averages", "individuals", "all"] = "averages"
    """
    Optional XPS region tokens (e.g. C1s, O1s). When non-empty, only VAMAS blocks
    whose ``xps_region`` is in this list are kept (after ``vms_spectrum_mode``).
    None or empty means no region restriction.
    """
    xps_regions: list[str] | None = None
    """
    Optional explicit multi-spectrum block indices per relative_path.
    When provided for a path, kept indices are intersected with this list
    (after mode / region filters). Paths omitted use mode/regions only.
    """
    record_indices: dict[str, list[int]] | None = None

    @model_validator(mode="after")
    def default_or_strip_display_name(self) -> DatasetCreateRequest:
        raw = self.metadata.name
        s = (raw or "").strip()
        if s:
            self.metadata = self.metadata.model_copy(update={"name": s})
        else:
            self.metadata = self.metadata.model_copy(
                update={"name": f"Unnamed dataset {uuid4().hex[:8]}"}
            )
        return self


class SkippedUpload(BaseModel):
    """A selected upload path that could not be turned into spectra for this dataset."""

    relative_path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class DatasetCreateResponse(BaseModel):
    dataset: Dataset
    skipped_files: list[SkippedUpload] = Field(default_factory=list)


class DatasetListItem(BaseModel):
    dataset_id: str = Field(min_length=1)
    count: int = Field(ge=0)
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)


class DatasetListResponse(BaseModel):
    items: list[DatasetListItem] = Field(default_factory=list)
    count: int = Field(ge=0)


class DatasetGetResponse(BaseModel):
    dataset: Dataset


class DatasetRestoreUploadsRequest(BaseModel):
    force_copy: bool = False


class DatasetRestoreUploadsItem(BaseModel):
    original_relative_path: str
    relative_path: str
    filename: str
    status: str = Field(pattern="^(restored|reactivated|already_active|missing)$")
    reason: str | None = None


class DatasetRestoreUploadsResponse(BaseModel):
    restored: list[DatasetRestoreUploadsItem] = Field(default_factory=list)
    reactivated: list[DatasetRestoreUploadsItem] = Field(default_factory=list)
    already_active: list[DatasetRestoreUploadsItem] = Field(default_factory=list)
    missing: list[DatasetRestoreUploadsItem] = Field(default_factory=list)


class DatasetImportResponse(BaseModel):
    dataset: Dataset
    imported_spectra: int = Field(ge=0)
    imported_blobs: int = Field(ge=0)
    imported_labels: int = Field(ge=0)


class DatasetMetricsRequest(BaseModel):
    # placeholder for later stages; keep contract stable
    metrics: list[str] = Field(default_factory=list)
    pipeline: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None

