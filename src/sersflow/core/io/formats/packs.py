"""Shared capability packs for format UI / filters."""

from __future__ import annotations

from sersflow.core.io.formats.types import CapabilityPack, FilterFieldDef, UiTreatment

_EXPERIMENTAL_COMMON: tuple[FilterFieldDef, ...] = (
    FilterFieldDef("sample", "Sample", "categorical", "experimental"),
    FilterFieldDef("gas", "Gas", "categorical", "experimental"),
    FilterFieldDef("ph", "pH", "categorical", "experimental"),
    FilterFieldDef("current_density_A_cm2", "Current density (A·cm⁻²)", "categorical", "experimental"),
    FilterFieldDef("potential_V", "Potential (V)", "categorical", "experimental"),
    FilterFieldDef("potential_ref", "Potential ref", "categorical", "experimental"),
    FilterFieldDef("electrolyte", "Electrolyte", "categorical", "experimental"),
    FilterFieldDef("concentration_M", "Concentration (M)", "categorical", "experimental"),
)

_LASER_FIELDS: tuple[FilterFieldDef, ...] = (
    FilterFieldDef("laser_nm", "Laser (nm)", "categorical", "experimental"),
    FilterFieldDef("laser_power_pct", "Laser power (%)", "categorical", "experimental"),
)

_AXIS_FIELDS: tuple[FilterFieldDef, ...] = (
    FilterFieldDef("axis_map_x", "Map X", "numeric", "axis"),
    FilterFieldDef("axis_map_y", "Map Y", "numeric", "axis"),
    FilterFieldDef("axis_time_s", "Time (s)", "numeric", "axis"),
)

_XPS_STRUCTURAL: tuple[FilterFieldDef, ...] = (
    FilterFieldDef("xps_region", "XPS region", "categorical", "structural"),
    FilterFieldDef("spectrum_role", "Spectrum role", "categorical", "structural"),
    FilterFieldDef("xps_species", "Species", "categorical", "structural"),
    FilterFieldDef("xps_transition", "Transition", "categorical", "structural"),
    FilterFieldDef("block_name", "Block name", "categorical", "structural"),
    FilterFieldDef("excitation_energy_eV", "Excitation energy (eV)", "numeric", "structural"),
    FilterFieldDef("replicate_index", "Replicate index", "numeric", "structural"),
)


SINGLE_XY = CapabilityPack(
    id="single_xy",
    capabilities=frozenset(),
    filter_fields=_EXPERIMENTAL_COMMON + _LASER_FIELDS,
    ui=UiTreatment(
        plot_mode="xy",
        default_x_label=None,
        default_y_label="Intensity",
        create_dataset_hints=("Tabular XY text with a recognized axis header.",),
    ),
)

MAP_OR_SERIES_RAMAN = CapabilityPack(
    id="map_or_series_raman",
    capabilities=frozenset({"map_axes", "time_axis", "wavenumber_x"}),
    filter_fields=_EXPERIMENTAL_COMMON + _LASER_FIELDS + _AXIS_FIELDS,
    ui=UiTreatment(
        plot_mode="map",
        default_x_label="Wavenumber (cm⁻¹)",
        default_y_label="Intensity",
        create_dataset_hints=("Renishaw WDF maps/series.",),
    ),
)

MULTI_BLOCK_XPS = CapabilityPack(
    id="multi_block_xps",
    capabilities=frozenset(
        {
            "multi_block",
            "xps_regions",
            "spectrum_roles",
            "pass_energy",
            "binding_energy_x",
        }
    ),
    filter_fields=_XPS_STRUCTURAL + _EXPERIMENTAL_COMMON,
    ui=UiTreatment(
        show_block_picker=True,
        show_spectrum_mode=True,
        show_region_filter=True,
        plot_mode="multi_overlay",
        default_x_label="Binding energy (eV)",
        default_y_label="Intensity (counts)",
        create_dataset_hints=(
            "Multi-block XPS: choose averages/individuals and optional regions.",
        ),
    ),
)

NXS_SKIP_SUMMARY = CapabilityPack(
    id="nxs_skip_summary",
    capabilities=frozenset({"multi_block", "xps_regions", "binding_energy_x"}),
    filter_fields=_XPS_STRUCTURAL + _EXPERIMENTAL_COMMON,
    ui=UiTreatment(
        show_block_picker=True,
        show_spectrum_mode=True,
        show_region_filter=True,
        show_skip_summary=True,
        plot_mode="multi_overlay",
        default_x_label="Binding energy (eV)",
        default_y_label="Intensity (counts)",
        create_dataset_hints=("NeXus XPS: non-BE regions may be skipped on load.",),
    ),
)

# Public export for filter_catalog / plot (experimental labels).
EXPERIMENTAL_FIELD_LABELS: dict[str, tuple[str, str]] = {
    f.key: (f.label, f.kind) for f in (_EXPERIMENTAL_COMMON + _LASER_FIELDS)
}

AXIS_FIELD_CATALOG: list[tuple[str, str, str]] = [
    (f.key, f.label, f.kind) for f in _AXIS_FIELDS
]

XPS_STRUCTURAL_FIELD_CATALOG: list[tuple[str, str, str]] = [
    (f.key, f.label, f.kind) for f in _XPS_STRUCTURAL
]

XPS_STRUCTURAL_FILTER_KEYS = frozenset(f.key for f in _XPS_STRUCTURAL)
