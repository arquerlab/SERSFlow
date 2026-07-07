from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.plot import (
    MapInfoResponse,
    MapPointsPlotRequest,
    PlotFigureResponse,
    PlotKindsResponse,
    SeriesHeatmapRequest,
    SeriesInfoResponse,
    SeriesPointsPlotRequest,
    SpectrumPlotRequest,
)
from sersflow.client.http import request_bytes, request_json
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class PlotResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def kinds(self) -> PlotKindsResponse:
        data = request_json(self._root.http, "GET", "/plot/kinds")
        return PlotKindsResponse.model_validate(data)

    def spectrum(self, payload: SpectrumPlotRequest) -> PlotFigureResponse:
        data = request_json(self._root.http, "POST", "/plot/spectrum", json_body=dump_json(payload))
        return PlotFigureResponse.model_validate(data)

    def series_heatmap(self, payload: SeriesHeatmapRequest) -> PlotFigureResponse:
        data = request_json(self._root.http, "POST", "/plot/series-heatmap", json_body=dump_json(payload))
        return PlotFigureResponse.model_validate(data)

    def series_info(self, relative_path: str, *, max_points: int = 500) -> SeriesInfoResponse:
        data = request_json(
            self._root.http,
            "GET",
            "/plot/series-info",
            params={"relative_path": relative_path, "max_points": max_points},
        )
        return SeriesInfoResponse.model_validate(data)

    def series_points(self, payload: SeriesPointsPlotRequest) -> PlotFigureResponse:
        data = request_json(self._root.http, "POST", "/plot/series-points", json_body=dump_json(payload))
        return PlotFigureResponse.model_validate(data)

    def series_value(self, relative_path: str, index: int) -> dict[str, Any]:
        data = request_json(
            self._root.http,
            "GET",
            "/plot/series-value",
            params={"relative_path": relative_path, "index": index},
        )
        return dict(data) if isinstance(data, dict) else {}

    def map_info(self, relative_path: str, *, max_dim: int = 80) -> MapInfoResponse:
        data = request_json(
            self._root.http,
            "GET",
            "/plot/map-info",
            params={"relative_path": relative_path, "max_dim": max_dim},
        )
        return MapInfoResponse.model_validate(data)

    def map_preview_image(self, relative_path: str, *, crop_to_map: bool = False) -> bytes:
        return request_bytes(
            self._root.http,
            "GET",
            "/plot/map-preview-image",
            params={"relative_path": relative_path, "crop_to_map": crop_to_map},
        )

    def map_points(self, payload: MapPointsPlotRequest) -> PlotFigureResponse:
        data = request_json(self._root.http, "POST", "/plot/map-points", json_body=dump_json(payload))
        return PlotFigureResponse.model_validate(data)
