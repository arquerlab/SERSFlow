from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Shapes(BaseModel):
    xdata: list[int] | None = None
    spectra: list[int] | None = None
    axis3: list[int] | None = None
    axis4: list[int] | None = None


class Preview(BaseModel):
    xdata: Any | None = None
    spectra: Any | None = None
    axis3: Any | None = None
    axis4: Any | None = None


class IoLoadResponse(BaseModel):
    filename: str | None = None
    kind: Literal["unknown", "spectrum", "series", "map"] = "unknown"
    shapes: Shapes
    preview: Preview


class UploadRegistryItem(BaseModel):
    batch_id: str
    filename: str
    relative_path: str
    size_bytes: int = Field(ge=0)
    saved_at: str
    modified_utc: str | None = None
    wn_min: float | None = None
    wn_max: float | None = None
    spectrum_count: int | None = None
    labels: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Suggested keys: sample, gas, ph, current_density_A_cm2 (A·cm⁻²), potential_V "
            "(RHE scale, V), potential_ref (VRHE or OCP), laser_nm, laser_power_pct, "
            "electrolyte (compound name), concentration_M (molar). Legacy keys may still appear."
        ),
    )


class UploadListResponse(BaseModel):
    items: list[UploadRegistryItem]
    count: int = Field(ge=0)


class UnloadRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)


class PurgeRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)


class PurgePreviewRequest(BaseModel):
    relative_paths: list[str] | None = None
    hidden_only: bool = True


class PurgePreviewItem(BaseModel):
    relative_path: str
    filename: str = ""
    size_bytes: int = Field(ge=0)
    exists: bool = True
    blocked_count: int = Field(default=0, ge=0)


class PurgePreviewResponse(BaseModel):
    items: list[PurgePreviewItem] = Field(default_factory=list)
    total_files: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    blocked: dict[str, int] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)


class PurgeResponse(BaseModel):
    deleted: int = Field(ge=0)
    missing: int = Field(ge=0)
    blocked: dict[str, int] = Field(default_factory=dict)


class UnloadedRegistryItem(BaseModel):
    batch_id: str
    filename: str
    relative_path: str
    size_bytes: int = Field(ge=0)
    saved_at: str
    modified_utc: str | None = None
    unloaded_at: str = ""
    labels: dict[str, Any] = Field(default_factory=dict)


class UnloadedListResponse(BaseModel):
    items: list[UnloadedRegistryItem]
    count: int = Field(ge=0)


class UpdateLabelsRequest(BaseModel):
    relative_path: str = Field(min_length=1)
    labels: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Label dict to store. Prefer: current_density_A_cm2, concentration_M, electrolyte, "
            "plus other keys as in GET /io/uploads. Legacy keys may be accepted."
        ),
    )


class AutoLabelsRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)

