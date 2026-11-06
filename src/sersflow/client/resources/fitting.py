from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.fitting import FitRequest, FitResponse, FittingModelsResponse
from sersflow.client.http import request_json
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class FittingResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def models(self) -> FittingModelsResponse:
        data = request_json(self._root.http, "GET", "/fitting/models")
        return FittingModelsResponse.model_validate(data)

    def validate_links(self, components: list[dict[str, Any]], param_links: list[dict[str, Any]]) -> dict[str, Any]:
        data = request_json(
            self._root.http,
            "POST",
            "/fitting/validate-links",
            json_body={"components": components, "param_links": param_links},
        )
        return dict(data) if isinstance(data, dict) else {}

    def test_peak_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = request_json(self._root.http, "POST", "/fitting/test-peak-model", json_body=payload)
        return dict(data) if isinstance(data, dict) else {}

    # ---- reference-spectrum library (M1) ----
    def list_references(self, q: str | None = None) -> dict[str, Any]:
        return dict(request_json(self._root.http, "GET", "/references", params={"q": q} if q else None))

    def get_reference(self, reference_id: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "GET", f"/references/{reference_id}"))

    def create_reference(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(request_json(self._root.http, "POST", "/references", json_body=payload))

    def create_reference_from_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(request_json(self._root.http, "POST", "/references/from-dataset", json_body=payload))

    def import_reference(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(request_json(self._root.http, "POST", "/references/import", json_body=payload))

    def delete_reference(self, reference_id: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "DELETE", f"/references/{reference_id}"))

    # ---- fit history (X1) ----
    def list_history(self, scope_key: str, *, include_params: bool = True, limit: int = 100) -> dict[str, Any]:
        return dict(
            request_json(
                self._root.http,
                "GET",
                "/fitting/history",
                params={"scope_key": scope_key, "include_params": include_params, "limit": limit},
            )
        )

    def add_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(request_json(self._root.http, "POST", "/fitting/history", json_body=payload))

    def get_history(self, history_id: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "GET", f"/fitting/history/{history_id}"))

    def compare_history(self, a: str, b: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "GET", "/fitting/history/compare", params={"a": a, "b": b}))

    def update_history(self, history_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(request_json(self._root.http, "PATCH", f"/fitting/history/{history_id}", json_body=payload))

    def delete_history(self, history_id: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "DELETE", f"/fitting/history/{history_id}"))

    def clear_history(self, scope_key: str) -> dict[str, Any]:
        return dict(request_json(self._root.http, "DELETE", "/fitting/history", params={"scope_key": scope_key}))

    def fit(self, payload: FitRequest) -> FitResponse:
        data = request_json(self._root.http, "POST", "/fitting/fit", json_body=dump_json(payload))
        return FitResponse.model_validate(data)
