from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile

from sersflow.api.schemas.io import UnloadRequest, UploadListResponse
from sersflow.core.io.upload_registry import (
    append_upload_registry,
    make_registry_item,
    new_batch_dir,
    read_upload_registry,
    unload_files_from_registry,
    upload_root,
)


router = APIRouter(prefix="/io", tags=["io"])

def _format_mib_3(bytes_count: int | float) -> str:
    mb = (float(bytes_count) if bytes_count else 0.0) / (1024.0 * 1024.0)
    if not (mb > 0.0):
        return "0.000 MB"
    return f"{mb:.3f} MB"


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> Response:
    """
    Upload multiple files and store them on disk.

    This endpoint does NOT parse files. It only saves them to an upload folder.
    """
    root_dir = upload_root()
    batch_id, batch_dir = new_batch_dir(root_dir)

    saved = 0
    total_bytes = 0
    registry_items: list[dict[str, Any]] = []

    try:
        for f in files:
            if not f.filename:
                continue
            name = Path(f.filename).name
            target = batch_dir / name
            with target.open("wb") as out_f:
                shutil.copyfileobj(f.file, out_f)
            saved += 1
            try:
                size = target.stat().st_size
                total_bytes += size
            except OSError:
                size = 0

            registry_items.append(
                make_registry_item(batch_id=batch_id, filename=name, size_bytes=int(size)).to_dict()
            )
    finally:
        for f in files:
            try:
                f.file.close()
            except Exception:
                pass

    append_upload_registry(root_dir, registry_items)
    return Response(
        content=f"Uploaded {saved} file(s) to batch {batch_id} ({_format_mib_3(total_bytes)}).",
        media_type="text/plain",
    )


@router.get("/uploads", response_model=UploadListResponse)
def list_uploaded_files(limit: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
    root_dir = upload_root()
    items = read_upload_registry(root_dir)
    limited = items[-limit:]
    return {"items": limited, "count": min(len(items), limit)}


@router.post("/unload")
def unload_files(payload: UnloadRequest) -> Response:
    root_dir = upload_root()
    try:
        deleted, missing = unload_files_from_registry(
            upload_root_dir=root_dir, relative_paths=payload.relative_paths
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return Response(
        content=f"Unloaded {deleted} file(s). Missing: {missing}.",
        media_type="text/plain",
    )

