from __future__ import annotations

from typing import TYPE_CHECKING

from sersflow.api.schemas.metrics import MetricsComputeRequest, MetricsComputeResponse
from sersflow.client.http import request_json
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class MetricsResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def compute(self, payload: MetricsComputeRequest) -> MetricsComputeResponse:
        data = request_json(self._root.http, "POST", "/metrics/compute", json_body=dump_json(payload))
        return MetricsComputeResponse.model_validate(data)
