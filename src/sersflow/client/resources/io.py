from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.io import (
    AutoLabelsRequest,
    PurgeRequest,
    PurgeResponse,
    UnloadRequest,
    UnloadedListResponse,
    UpdateLabelsRequest,
    UploadListResponse,
)
from sersflow.client.http import raise_for_response, request_json, request_multipart_upload, request_text
from sersflow.client.parsing import UploadResult, parse_upload_response
from sersflow.client.resources._common import _Base

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class IoResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def upload_folder(
        self,
        folder: Path | str,
        *,
        pattern: str = "*.txt",
        recursive: bool = True,
        base_dir: Path | str | None = None,
    ) -> UploadResult:
        folder_path = Path(folder)
        paths = sorted(folder_path.rglob(pattern) if recursive else folder_path.glob(pattern))
        return self.upload_files(paths, base_dir=base_dir or folder_path)

    def upload_files(self, paths: list[Path | str], *, base_dir: Path | str | None = None) -> UploadResult:
        if not paths:
            raise ValueError("paths must not be empty")
        upload_names: list[str] | None = None
        if base_dir is not None:
            b = Path(base_dir).resolve()
            upload_names = []
            for p in paths:
                pp = Path(p).resolve()
                try:
                    rel = pp.relative_to(b)
                    upload_names.append(rel.as_posix())
                except Exception:
                    upload_names.append(pp.name)

        r = request_multipart_upload(
            self._root.http,
            "/io/upload",
            file_field="files",
            paths=list(paths),
            upload_names=upload_names,
        )
        raise_for_response(r)
        return parse_upload_response(r.text)

    def list_uploads(self, limit: int = 5000) -> UploadListResponse:
        data = request_json(self._root.http, "GET", "/io/uploads", params={"limit": limit})
        return UploadListResponse.model_validate(data)

    def list_unloaded(self, limit: int = 5000) -> UnloadedListResponse:
        data = request_json(self._root.http, "GET", "/io/unloaded", params={"limit": limit})
        return UnloadedListResponse.model_validate(data)

    def update_labels(self, payload: UpdateLabelsRequest, *, use_post: bool = False) -> dict[str, Any]:
        method = "POST" if use_post else "PUT"
        body = payload.model_dump(mode="json", exclude_none=True)
        data = request_json(self._root.http, method, "/io/labels", json_body=body)
        return dict(data) if isinstance(data, dict) else {"ok": data}

    def auto_labels(self, payload: AutoLabelsRequest) -> dict[str, Any]:
        body = payload.model_dump(mode="json", exclude_none=True)
        data = request_json(self._root.http, "POST", "/io/labels/auto", json_body=body)
        return dict(data) if isinstance(data, dict) else {}

    def unload(self, payload: UnloadRequest) -> str:
        body = payload.model_dump(mode="json", exclude_none=True)
        return request_text(self._root.http, "POST", "/io/unload", json_body=body)

    def purge(self, payload: PurgeRequest) -> PurgeResponse:
        body = payload.model_dump(mode="json", exclude_none=True)
        data = request_json(self._root.http, "POST", "/io/purge", json_body=body)
        return PurgeResponse.model_validate(data)
