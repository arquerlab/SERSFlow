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

    def fit(self, payload: FitRequest) -> FitResponse:
        data = request_json(self._root.http, "POST", "/fitting/fit", json_body=dump_json(payload))
        return FitResponse.model_validate(data)
