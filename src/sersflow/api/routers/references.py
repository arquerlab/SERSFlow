"""Reference-spectrum library (M1): measured spectra used as fit components (CasaXPS LLS basis). Per user."""

from __future__ import annotations

import csv
import io
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from sersflow.api.deps import current_user_id
from sersflow.infra.reference_spectra_store import (
    create_reference,
    delete_reference,
    get_reference,
    list_references,
    update_reference,
)

router = APIRouter(prefix="/references", tags=["references"])


class ReferenceCreateRequest(BaseModel):
    """A processed spectrum (e.g. from the Prepare preview after calibration and background subtraction)."""

    name: str = Field(min_length=1)
    x: list[float]
    y: list[float]
    notes: str = ""
    technique_family: str = "xps"
    source: dict[str, Any] = Field(
        default_factory=dict,
        description="Provenance: dataset_id, spectrum_id, pipeline steps / hash applied, after_step, ...",
    )
    x_min: float | None = None
    x_max: float | None = None


class ReferenceFromDatasetRequest(BaseModel):
    """A dataset spectrum as loaded (raw, no processing)."""

    name: str = Field(min_length=1)
    dataset_id: str
    spectrum_id: str
    notes: str = ""
    x_min: float | None = None
    x_max: float | None = None


class ReferenceImportRequest(BaseModel):
    """Two-column text (energy, intensity; comma, tab, semicolon or space separated; '#' comments)."""

    name: str = Field(min_length=1)
    content: str
    filename: str | None = None
    notes: str = ""
    technique_family: str = "xps"


class ReferenceUpdateRequest(BaseModel):
    name: str | None = None
    notes: str | None = None


def _window(x: list[float], y: list[float], lo: float | None, hi: float | None) -> tuple[list[float], list[float]]:
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    keep = np.ones(xa.size, dtype=bool)
    if lo is not None:
        keep &= xa >= lo
    if hi is not None:
        keep &= xa <= hi
    return xa[keep].tolist(), ya[keep].tolist()


def _create(user_id: str, **kw: Any) -> dict[str, Any]:
    try:
        ref = create_reference(owner_user_id=user_id, **kw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {**ref.summary(), "x": ref.x, "y": ref.y}


@router.get("")
def get_references(request: Request, q: str | None = None, limit: int = 200) -> dict[str, Any]:
    refs = list_references(owner_user_id=current_user_id(request), q=q, limit=limit)
    return {"items": [r.summary() for r in refs], "count": len(refs)}


@router.get("/{reference_id}")
def get_reference_endpoint(reference_id: str, request: Request) -> dict[str, Any]:
    ref = get_reference(reference_id, owner_user_id=current_user_id(request))
    if ref is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    return {**ref.summary(), "x": ref.x, "y": ref.y}


@router.post("")
def post_reference(payload: ReferenceCreateRequest, request: Request) -> dict[str, Any]:
    x, y = _window(payload.x, payload.y, payload.x_min, payload.x_max)
    return _create(
        current_user_id(request),
        name=payload.name,
        x=x,
        y=y,
        notes=payload.notes,
        technique_family=payload.technique_family,
        source={"kind": "processed", **payload.source},
    )


@router.post("/from-dataset")
def post_reference_from_dataset(payload: ReferenceFromDatasetRequest, request: Request) -> dict[str, Any]:
    from sersflow.api.routers.fitting import _resolve_target_xy
    from sersflow.api.schemas.fitting import FitSpectrumRef
    from sersflow.api.services.ownership import get_dataset_for_user

    user_id = current_user_id(request)
    ds = get_dataset_for_user(payload.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    ref = next((s for s in ds.spectra if s.spectrum_id == payload.spectrum_id), None)
    if ref is None:
        raise HTTPException(status_code=404, detail="Spectrum not found in dataset")
    xy = _resolve_target_xy(FitSpectrumRef(spectrum=ref), owner_user_id=user_id)
    x, y = _window(np.asarray(xy.x).tolist(), np.asarray(xy.y).tolist(), payload.x_min, payload.x_max)
    return _create(
        user_id,
        name=payload.name,
        x=x,
        y=y,
        notes=payload.notes,
        technique_family=str(getattr(ds.metadata, "technique_family", None) or "xps"),
        source={
            "kind": "dataset_raw",
            "dataset_id": payload.dataset_id,
            "spectrum_id": payload.spectrum_id,
            "relative_path": str(ref.original_relative_path or ref.relative_path),
            "record_index": ref.record_index,
            "x_min": payload.x_min,
            "x_max": payload.x_max,
        },
    )


def parse_two_column_text(content: str) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for line in io.StringIO(content):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        row = next(csv.reader([s.replace(";", ",").replace("\t", ",")]))
        parts = [p.strip() for p in row if p.strip()] if len(row) > 1 else s.split()
        try:
            a, b = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            continue  # header or malformed line
        xs.append(a)
        ys.append(b)
    if len(xs) < 3:
        raise ValueError("could not read at least 3 numeric (energy, intensity) rows")
    return xs, ys


@router.post("/import")
def post_reference_import(payload: ReferenceImportRequest, request: Request) -> dict[str, Any]:
    try:
        x, y = parse_two_column_text(payload.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _create(
        current_user_id(request),
        name=payload.name,
        x=x,
        y=y,
        notes=payload.notes,
        technique_family=payload.technique_family,
        source={"kind": "text_import", "filename": payload.filename},
    )


@router.patch("/{reference_id}")
def patch_reference(reference_id: str, payload: ReferenceUpdateRequest, request: Request) -> dict[str, Any]:
    ref = update_reference(reference_id, owner_user_id=current_user_id(request), name=payload.name, notes=payload.notes)
    if ref is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    return ref.summary()


@router.delete("/{reference_id}")
def delete_reference_endpoint(reference_id: str, request: Request) -> dict[str, Any]:
    if not delete_reference(reference_id, owner_user_id=current_user_id(request)):
        raise HTTPException(status_code=404, detail="Reference not found")
    return {"deleted": True}
