from __future__ import annotations

from typing import Any

import httpx

from sersflow.client.resources.analysis import AnalysisResource
from sersflow.client.resources.datasets import DatasetsResource
from sersflow.client.resources.explore import ExploreResource
from sersflow.client.resources.fitting import FittingResource
from sersflow.client.resources.io import IoResource
from sersflow.client.resources.meta import MetaResource
from sersflow.client.resources.metrics import MetricsResource
from sersflow.client.resources.pipeline_run import PipelineResource
from sersflow.client.resources.pipelines_lib import PipelinesLibResource
from sersflow.client.resources.plot import PlotResource
from sersflow.client.resources.raw import RawResource
from sersflow.client.resources.sessions import SessionsResource


class SersflowClient:
    """
    Synchronous HTTP client for the SERSFlow FastAPI service.

    Install the optional dependency: ``pip install "sersflow[client]"``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        headers = dict(default_headers or {})
        client_kw: dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "timeout": httpx.Timeout(timeout),
            "headers": headers,
            "follow_redirects": True,
        }
        if transport is not None:
            client_kw["transport"] = transport
        self.http = httpx.Client(**client_kw)
        self.meta = MetaResource(self)
        self.io = IoResource(self)
        self.datasets = DatasetsResource(self)
        self.pipeline = PipelineResource(self)
        self.pipelines = PipelinesLibResource(self)
        self.metrics = MetricsResource(self)
        self.sessions = SessionsResource(self)
        self.fitting = FittingResource(self)
        self.plot = PlotResource(self)
        self.analysis = AnalysisResource(self)
        self.explore = ExploreResource(self)
        self.raw = RawResource(self)

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> SersflowClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
