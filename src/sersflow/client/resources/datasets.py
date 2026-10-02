from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.datasets import (
    DatasetCreateRequest,
    DatasetCreateResponse,
    DatasetGetResponse,
    DatasetImportResponse,
    DatasetListResponse,
    DatasetRestoreUploadsRequest,
    DatasetRestoreUploadsResponse,
)
from sersflow.api.schemas.metrics import DatasetMetricsRequest, DatasetMetricsResponse
from sersflow.client.http import request_json, stream_response_to_file
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class DatasetsResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def create(self, request: DatasetCreateRequest) -> DatasetCreateResponse:
        data = request_json(self._root.http, "POST", "/datasets", json_body=dump_json(request))
        return DatasetCreateResponse.model_validate(data)

    def list(self, limit: int = 50, offset: int = 0) -> DatasetListResponse:
        data = request_json(self._root.http, "GET", "/datasets", params={"limit": limit, "offset": offset})
        return DatasetListResponse.model_validate(data)

    def get(self, dataset_id: str) -> DatasetGetResponse:
        data = request_json(self._root.http, "GET", f"/datasets/{dataset_id}")
        return DatasetGetResponse.model_validate(data)

    def spectrum_axes(
        self,
        dataset_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        data = request_json(
            self._root.http,
            "GET",
            f"/datasets/{dataset_id}/spectrum-axes",
            params={"limit": limit, "offset": offset},
        )
        return dict(data) if isinstance(data, dict) else {}

    def xps_regions(self, dataset_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "GET", f"/datasets/{dataset_id}/xps-regions")
        return dict(data) if isinstance(data, dict) else {}

    def filter_fields(self, dataset_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "GET", f"/datasets/{dataset_id}/filter-fields")
        return dict(data) if isinstance(data, dict) else {}

    def export_to_file(self, dataset_id: str, dest: Path | str) -> None:
        stream_response_to_file(
            self._root.http,
            "GET",
            f"/datasets/{dataset_id}/export",
            dest,
        )

    def import_package(self, path: Path | str) -> DatasetImportResponse:
        p = Path(path)
        with p.open("rb") as fh:
            r = self._root.http.post(
                "/datasets/import",
                files={"file": (p.name, fh, "application/octet-stream")},
            )
        from sersflow.client.http import raise_for_response

        raise_for_response(r)
        return DatasetImportResponse.model_validate(r.json())

    def restore_uploads(
        self,
        dataset_id: str,
        payload: DatasetRestoreUploadsRequest | None = None,
    ) -> DatasetRestoreUploadsResponse:
        body = dump_json(payload) if payload is not None else {}
        data = request_json(
            self._root.http,
            "POST",
            f"/datasets/{dataset_id}/restore-uploads",
            json_body=body,
        )
        return DatasetRestoreUploadsResponse.model_validate(data)

    def delete(self, dataset_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "DELETE", f"/datasets/{dataset_id}")
        return dict(data) if isinstance(data, dict) else {}

    def clear_all(self) -> dict[str, Any]:
        raise NotImplementedError(
            "Bulk DELETE /datasets was removed for safety. Delete datasets individually with delete()."
        )

    def compute_metrics(self, dataset_id: str, payload: DatasetMetricsRequest) -> DatasetMetricsResponse:
        data = request_json(
            self._root.http,
            "POST",
            f"/datasets/{dataset_id}/metrics",
            json_body=payload.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        return DatasetMetricsResponse.model_validate(data)
