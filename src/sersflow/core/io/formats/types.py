"""Types for the file-format registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from sersflow.core.io.technique import TechniqueFamily
from sersflow.core.models.datasets import Dataset

FilterKind = Literal["categorical", "numeric"]
FilterSource = Literal["structural", "experimental", "axis"]
PlotMode = Literal["xy", "multi_overlay", "map"]
TechniqueOrSniff = TechniqueFamily | Literal["sniff"]


@dataclass(frozen=True)
class FilterFieldDef:
    key: str
    label: str
    kind: FilterKind
    source: FilterSource


@dataclass(frozen=True)
class UiTreatment:
    """How Uploads / raw viz / Prepare should behave for a capability pack."""

    show_block_picker: bool = False
    show_spectrum_mode: bool = False
    show_region_filter: bool = False
    show_skip_summary: bool = False
    plot_mode: PlotMode = "xy"
    default_x_label: str | None = None
    default_y_label: str | None = None
    create_dataset_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityPack:
    id: str
    capabilities: frozenset[str]
    filter_fields: tuple[FilterFieldDef, ...]
    ui: UiTreatment


@dataclass(frozen=True)
class EnrichResult:
    labels: dict[str, Any]
    block_map: dict[str, dict[str, Any]] | None
    dataset: Dataset


EnrichFn = Callable[[Path, Dataset, dict[str, Any] | None], EnrichResult]
LoaderFn = Callable[[Path], Dataset]


@dataclass(frozen=True)
class FormatSpec:
    id: str
    label: str
    suffixes: tuple[str, ...]
    technique: TechniqueOrSniff
    dataset_kinds: frozenset[str]
    packs: tuple[CapabilityPack, ...]
    loader: LoaderFn
    docs: str
    enrich: EnrichFn | None = None

    def all_capabilities(self) -> frozenset[str]:
        out: set[str] = set()
        for pack in self.packs:
            out |= set(pack.capabilities)
        return frozenset(out)

    def merged_ui(self) -> UiTreatment:
        """OR-merge UI flags across packs; prefer first non-null labels / plot_mode."""
        show_block = False
        show_mode = False
        show_region = False
        show_skip = False
        plot_mode: PlotMode = "xy"
        x_label: str | None = None
        y_label: str | None = None
        hints: list[str] = []
        for pack in self.packs:
            ui = pack.ui
            show_block = show_block or ui.show_block_picker
            show_mode = show_mode or ui.show_spectrum_mode
            show_region = show_region or ui.show_region_filter
            show_skip = show_skip or ui.show_skip_summary
            if ui.plot_mode != "xy":
                plot_mode = ui.plot_mode
            if x_label is None and ui.default_x_label:
                x_label = ui.default_x_label
            if y_label is None and ui.default_y_label:
                y_label = ui.default_y_label
            hints.extend(ui.create_dataset_hints)
        return UiTreatment(
            show_block_picker=show_block,
            show_spectrum_mode=show_mode,
            show_region_filter=show_region,
            show_skip_summary=show_skip,
            plot_mode=plot_mode,
            default_x_label=x_label,
            default_y_label=y_label,
            create_dataset_hints=tuple(hints),
        )

    def all_filter_fields(self) -> tuple[FilterFieldDef, ...]:
        seen: set[str] = set()
        out: list[FilterFieldDef] = []
        for pack in self.packs:
            for f in pack.filter_fields:
                if f.key in seen:
                    continue
                seen.add(f.key)
                out.append(f)
        return tuple(out)

    def to_public(self) -> dict[str, Any]:
        ui = self.merged_ui()
        tech = None if self.technique == "sniff" else self.technique
        return {
            "id": self.id,
            "label": self.label,
            "suffixes": list(self.suffixes),
            "technique_family": tech,
            "technique_sniff": self.technique == "sniff",
            "dataset_kinds": sorted(self.dataset_kinds),
            "capabilities": sorted(self.all_capabilities()),
            "ui": {
                "show_block_picker": ui.show_block_picker,
                "show_spectrum_mode": ui.show_spectrum_mode,
                "show_region_filter": ui.show_region_filter,
                "show_skip_summary": ui.show_skip_summary,
                "plot_mode": ui.plot_mode,
                "default_x_label": ui.default_x_label,
                "default_y_label": ui.default_y_label,
                "create_dataset_hints": list(ui.create_dataset_hints),
            },
            "filter_fields": [
                {"key": f.key, "label": f.label, "kind": f.kind, "source": f.source}
                for f in self.all_filter_fields()
            ],
            "docs": self.docs,
        }
