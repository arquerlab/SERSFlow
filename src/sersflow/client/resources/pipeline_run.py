from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.pipeline import (
    PipelineRunFinalResponse,
    PipelineRunMetricsResponse,
    PipelineRunRequest,
    PipelineSweepRequest,
    PipelineSweepResponse,
)
from sersflow.client.http import request_json
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class PipelineResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def baseline_methods(self) -> dict[str, Any]:
        data = request_json(self._root.http, "GET", "/pipeline/baseline-methods")
        return dict(data) if isinstance(data, dict) else {}

    def run(self, payload: PipelineRunRequest) -> PipelineRunFinalResponse | PipelineRunMetricsResponse:
        data = request_json(self._root.http, "POST", "/pipeline/run", json_body=dump_json(payload))
        try:
            kind = str(getattr(payload.return_, "kind", "") or "")
        except Exception:
            kind = ""
        if kind == "metrics_only":
            return PipelineRunMetricsResponse.model_validate(data)
        if kind == "final":
            return PipelineRunFinalResponse.model_validate(data)

        if isinstance(data, dict) and "items" in data:
            sample = data["items"][0] if data["items"] else {}
            if isinstance(sample, dict) and "metrics" in sample:
                return PipelineRunMetricsResponse.model_validate(data)
        return PipelineRunFinalResponse.model_validate(data)

    def sweep(self, payload: PipelineSweepRequest) -> PipelineSweepResponse:
        data = request_json(self._root.http, "POST", "/pipeline/sweep", json_body=dump_json(payload))
        return PipelineSweepResponse.model_validate(data)
