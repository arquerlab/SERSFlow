from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.pipelines import (
    PipelineCreateRequest,
    PipelineCreateResponse,
    PipelineGetResponse,
    PipelineListResponse,
    PipelineUpdateRequest,
    PipelineUpdateResponse,
)
from sersflow.client.http import request_json
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class PipelinesLibResource(_Base):
    """Saved pipeline definitions (library), prefix ``/pipelines``."""

    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def create(self, payload: PipelineCreateRequest, *, overwrite: bool = False) -> PipelineCreateResponse:
        data = request_json(
            self._root.http,
            "POST",
            "/pipelines",
            params={"overwrite": overwrite},
            json_body=dump_json(payload),
        )
        return PipelineCreateResponse.model_validate(data)

    def list(self, *, limit: int = 50, offset: int = 0, q: str | None = None) -> PipelineListResponse:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q is not None:
            params["q"] = q
        data = request_json(self._root.http, "GET", "/pipelines", params=params)
        return PipelineListResponse.model_validate(data)

    def get(self, pipeline_id: str) -> PipelineGetResponse:
        data = request_json(self._root.http, "GET", f"/pipelines/{pipeline_id}")
        return PipelineGetResponse.model_validate(data)

    def update(self, pipeline_id: str, payload: PipelineUpdateRequest) -> PipelineUpdateResponse:
        data = request_json(self._root.http, "PUT", f"/pipelines/{pipeline_id}", json_body=dump_json(payload))
        return PipelineUpdateResponse.model_validate(data)

    def delete(self, pipeline_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "DELETE", f"/pipelines/{pipeline_id}")
        return dict(data) if isinstance(data, dict) else {}
