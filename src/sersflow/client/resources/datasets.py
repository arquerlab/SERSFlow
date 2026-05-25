from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.datasets import (
    DatasetCreateRequest,
    DatasetCreateResponse,
    DatasetGetResponse,
    DatasetListResponse,
)
from sersflow.api.schemas.metrics import DatasetMetricsRequest, DatasetMetricsResponse
from sersflow.client.http import request_json
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

    def delete(self, dataset_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "DELETE", f"/datasets/{dataset_id}")
        return dict(data) if isinstance(data, dict) else {}

    def clear_all(self) -> dict[str, Any]:
        data = request_json(self._root.http, "DELETE", "/datasets")
        return dict(data) if isinstance(data, dict) else {}

    def compute_metrics(self, dataset_id: str, payload: DatasetMetricsRequest) -> DatasetMetricsResponse:
        data = request_json(
            self._root.http,
            "POST",
            f"/datasets/{dataset_id}/metrics",
            json_body=payload.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        return DatasetMetricsResponse.model_validate(data)
