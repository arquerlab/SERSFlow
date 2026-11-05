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
    target_component_id: str | None = None
    """Required for every mode except expr."""
    target_key: str | None = None
    mode: Literal["equal", "scale", "offset", "area_ratio", "expr"] = "equal"
    scale: float | None = None
    offset: float | None = None
    ratio: float | None = None
    """Only for mode=area_ratio: dependent AREA = ratio x driver AREA (amp links only)."""
    expr: str | None = None
    """Only for mode=expr (F4): e.g. ``{A.pos} + 0.5*({B.pos} - {A.pos})``; ``{A.area}`` = peak area."""
    defines: Literal["value", "area"] | None = None
    """mode=expr on an amp parameter: ``area`` makes the expression the peak AREA (amp solved through its shape)."""


class FwhmColumnFallback(BaseModel):
    peak: str
    requested_column: str
    used_column: str | None = None
    """None = no FWHM column at all; width seeded with 1.0 eV."""


class PassEnergyResolution(BaseModel):
    """How the recipe pass-energy column was chosen (K3)."""

    recipe_id: str | None = None
    requested: int | None = None
    acquisition: int | None = None
    used: int
    source: Literal["request", "acquisition", "acquisition_closest", "default"]
    available: list[int] = Field(default_factory=list)
    fallback: bool = False
    """True when the dataset/requested PE column was not used for every peak."""
    fwhm_fallbacks: list[FwhmColumnFallback] = Field(default_factory=list)


class FittingRecipeApplyResponse(BaseModel):
    recipe_id: str
    # Null for recipes without pass-energy tables (e.g. Fermi edge).
    recipe_pass_energy: int | None = None
    pass_energy_resolution: PassEnergyResolution | None = None
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
    spin_orbit_partner: dict[str, Any] | None = None
    """F3: set when spin-orbit partners were added ({splitting_eV, subshell, component_ids})."""


class SpinOrbitPartnerRequest(BaseModel):
    """
    F3 "Create x 2": add the spin-orbit partner of one peak to fitting-step params.

    The partner (2p1/2, 3d3/2 or 4f5/2) copies the peak's line shape at +``splitting_eV`` and is linked as a doublet:
    position offset, FWHM equal (or ``fwhm_ratio``), line-shape parameters equal (``link_shape``) and the theoretical
    area ratio p 1:2, d 2:3, f 3:4 (``lock_area``).
    """

    params: dict[str, Any] = Field(description="Fitting-step params (components, p0, bounds_lower/upper, vary, param_links)")
    component_id: str
    splitting_eV: float = Field(gt=0, description="Partner binding energy minus main-peak binding energy (eV)")
    subshell: Literal["p", "d", "f"]
    partner_id: str | None = None
    lock_area: bool = True
    link_shape: bool = True
    fwhm_ratio: float | None = Field(default=None, gt=0, description="Partner FWHM / main FWHM; null = equal")


class SpinOrbitPartnerResponse(BaseModel):
    params: dict[str, Any]
    partner_id: str


class FittingRecipesResponse(BaseModel):
    source: dict[str, Any] = Field(default_factory=dict)
    method_defaults: list[MethodDefaultPublic] = Field(default_factory=list)
    compound_fits: list[CompoundFitPublic] = Field(default_factory=list)
    method_count: int = 0
    compound_fit_count: int = 0
