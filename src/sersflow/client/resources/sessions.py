from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.sessions import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionGetResponse,
    SessionListResponse,
    SessionPipelineUpdateRequest,
    SessionPipelineUpdateResponse,
    SessionRunRequest,
    SessionSubsetUpdateResponse,
    SubsetStrategy,
)
from sersflow.client.http import request_json
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class SessionsResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def list_for_dataset(self, dataset_id: str, *, limit: int = 50) -> SessionListResponse:
        data = request_json(self._root.http, "GET", "/sessions", params={"dataset_id": dataset_id, "limit": limit})
        return SessionListResponse.model_validate(data)

    def create(self, payload: SessionCreateRequest) -> SessionCreateResponse:
        data = request_json(self._root.http, "POST", "/sessions", json_body=dump_json(payload))
        return SessionCreateResponse.model_validate(data)

    def get(self, session_id: str) -> SessionGetResponse:
        data = request_json(self._root.http, "GET", f"/sessions/{session_id}")
        return SessionGetResponse.model_validate(data)

    def update_pipeline(self, session_id: str, payload: SessionPipelineUpdateRequest) -> SessionPipelineUpdateResponse:
        data = request_json(self._root.http, "PUT", f"/sessions/{session_id}/pipeline", json_body=dump_json(payload))
        return SessionPipelineUpdateResponse.model_validate(data)

    def update_subset(self, session_id: str, subset: SubsetStrategy) -> SessionSubsetUpdateResponse:
        data = request_json(self._root.http, "POST", f"/sessions/{session_id}/subset", json_body=dump_json(subset))
        return SessionSubsetUpdateResponse.model_validate(data)

    def run(self, session_id: str, payload: SessionRunRequest) -> dict[str, Any]:
        data = request_json(self._root.http, "POST", f"/sessions/{session_id}/run", json_body=dump_json(payload))
        return dict(data) if isinstance(data, dict) else {"items": data}
