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


class UploadListResponse(BaseModel):
    items: list[UploadRegistryItem]
    count: int = Field(ge=0)


class UnloadRequest(BaseModel):
    relative_paths: list[str] = Field(min_length=1)

