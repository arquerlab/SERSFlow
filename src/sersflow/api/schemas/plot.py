from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlotFigureResponse(BaseModel):
    figure: dict[str, Any]


class SpectrumPlotRequest(BaseModel):
    relative_path: str = Field(min_length=1)
    title: str | None = None


class SeriesHeatmapRequest(BaseModel):
    relative_path: str = Field(min_length=1)
    title: str | None = None


class SeriesInfoResponse(BaseModel):
    is_series: bool
    axis: list[float] = Field(default_factory=list)
    count: int = Field(ge=0)


class SeriesPointsPlotRequest(BaseModel):
    relative_path: str = Field(min_length=1)
    indices: list[int] = Field(min_length=1)
    title: str | None = None


class MapInfoResponse(BaseModel):
    is_map: bool
    x: list[float] = Field(default_factory=list)
    y: list[float] = Field(default_factory=list)
    index_grid: list[list[int | None]] = Field(default_factory=list)
    count: int = Field(ge=0)


class MapPointsPlotRequest(BaseModel):
    relative_path: str = Field(min_length=1)
    indices: list[int] = Field(min_length=1)
    title: str | None = None


class PlotKindsResponse(BaseModel):
    kinds: list[Literal["spectrum", "series_heatmap"]]

