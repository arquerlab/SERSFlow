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


class MultiBlockMeta(BaseModel):
    index: int = Field(ge=0)
    xps_region: str | None = None
    spectrum_role: str | None = None
    xps_species: str | None = None
    xps_transition: str | None = None
    block_name: str | None = None
    replicate_index: int | None = None
    excitation_energy_eV: float | None = None
    technique: str | None = None
    acquired_at: str | None = None
    # Experimental / electrochemical labels (from upload_labels.vms_spectra merge)
    sample: str | None = None
    gas: str | None = None
    ph: float | None = None
    current_density_A_cm2: float | None = None
    potential_V: float | None = None
    potential_ref: str | None = None
    electrolyte: str | None = None
    concentration_M: float | None = None
    laser_nm: float | None = None
    laser_power_pct: float | None = None


class MultiFilterField(BaseModel):
    id: str
    label: str
    kind: Literal["categorical", "numeric"]
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None


class MultiInfoResponse(BaseModel):
    is_multi: bool
    count: int = Field(ge=0)
    blocks: list[MultiBlockMeta] = Field(default_factory=list)
    fields: list[MultiFilterField] = Field(default_factory=list)


class MultiPointsPlotRequest(BaseModel):
    relative_path: str = Field(min_length=1)
    indices: list[int] = Field(min_length=1)
    title: str | None = None


class PlotKindsResponse(BaseModel):
    kinds: list[Literal["spectrum", "series_heatmap"]]

