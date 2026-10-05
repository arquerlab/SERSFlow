from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChemicalStateEntryPublic(BaseModel):
    section_id: str
    element: str
    line: str
    energy_kind: Literal["binding", "kinetic"]
    compound: str
    phase: str | None = None
    value_eV: float
    references: list[str] = Field(default_factory=list)
    raw_line: str | None = None
    page: int | None = None
    provenance: str | None = None
    source_detail: str | None = None
    auger_parameter: float | None = None
    fwhm_eV: float | None = None


class ChemicalStateSectionPublic(BaseModel):
    id: str
    element: str
    line: str
    energy_kind: Literal["binding", "kinetic"]
    entry_count: int
    entries: list[ChemicalStateEntryPublic] = Field(default_factory=list)


class ChemicalStatesResponse(BaseModel):
    source: dict[str, Any] = Field(default_factory=dict)
    sections: list[ChemicalStateSectionPublic] = Field(default_factory=list)
    entries: list[ChemicalStateEntryPublic] = Field(default_factory=list)
    entry_count: int = 0


class MethodDefaultPublic(BaseModel):
    id: str
    chapter: int
    instrument: str | None = None
    software: str | None = None
    background: str | None = None
    charge_ref: dict[str, Any] = Field(default_factory=dict)
    default_lineshape: dict[str, Any] = Field(default_factory=dict)
    metal_lineshape: dict[str, Any] = Field(default_factory=dict)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    gl_examples: list[dict[str, Any]] = Field(default_factory=list)
    procedure_markdown: str | None = None


class CompoundFitPublic(BaseModel):
    id: str
    element: str
    region: str
    compound: str
    source_table: str | None = None
    pdf_page: int | None = None
    pass_energies: list[int] = Field(default_factory=list)
    peaks: list[dict[str, Any]] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    spin_orbit_split_eV: float | None = None


class CompoundFitIndexItem(BaseModel):
    id: str
    element: str
    region: str
    compound: str
    source_table: str | None = None
    pass_energies: list[int] = Field(default_factory=list)
    label: str
    aliases: list[str] = Field(default_factory=list)


class FittingRecipesIndexResponse(BaseModel):
    items: list[CompoundFitIndexItem] = Field(default_factory=list)
    count: int = 0


class FittingComponentPublic(BaseModel):
    component_id: str
    component_type: str
    degree: int | None = None


class FittingParamLinkPublic(BaseModel):
    source_component_id: str
    source_key: str
    target_component_id: str
    target_key: str
    mode: Literal["equal", "scale", "offset"] = "equal"
    scale: float | None = None
    offset: float | None = None


class FittingRecipeApplyResponse(BaseModel):
    recipe_id: str
    # Null for recipes without pass-energy tables (e.g. Fermi edge).
    recipe_pass_energy: int | None = None
    xps_region: str = ""
    components: list[FittingComponentPublic] = Field(default_factory=list)
    p0: list[float] = Field(default_factory=list)
    bounds_lower: list[float | None] = Field(default_factory=list)
    bounds_upper: list[float | None] = Field(default_factory=list)
    vary: list[bool] = Field(default_factory=list)
    param_links: list[FittingParamLinkPublic] = Field(default_factory=list)
    initial_guess_mode: str | None = "auto"
    initial_area_ratios: str | None = None
    """Area1:Area2:... from recipe area_pct when all peaks specify percentages."""
    warnings: list[str] = Field(default_factory=list)


class FittingRecipesResponse(BaseModel):
    source: dict[str, Any] = Field(default_factory=dict)
    method_defaults: list[MethodDefaultPublic] = Field(default_factory=list)
    compound_fits: list[CompoundFitPublic] = Field(default_factory=list)
    method_count: int = 0
    compound_fit_count: int = 0
