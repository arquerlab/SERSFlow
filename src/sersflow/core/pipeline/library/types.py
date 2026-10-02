"""Types for the processing step library."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sersflow.core.io.technique import TechniqueFamily
from sersflow.core.pipeline.steps import StepImpl

StepCategory = Literal[
    "geometry",
    "denoise",
    "baseline",
    "calibrate",
    "fit",
    "features",
    "qc",
    "reference",
]
PaletteGroup = Literal[
    "Data Preparation",
    "Preprocessing",
    "Transformation",
    "Feature Extraction",
    "QC",
]
UiFieldKind = Literal["number", "int", "select", "bool", "text", "json"]


@dataclass(frozen=True)
class UiFieldSpec:
    key: str
    kind: UiFieldKind
    label: str
    description: str | None = None
    options: tuple[str, ...] | None = None

    def to_public(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
        }
        if self.description is not None:
            out["description"] = self.description
        if self.options is not None:
            out["options"] = list(self.options)
        return out


@dataclass(frozen=True)
class StepMethodUi:
    id: str
    label: str
    defaults: dict[str, Any] = field(default_factory=dict)
    fields: tuple[UiFieldSpec, ...] = ()

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "defaults": dict(self.defaults),
            "fields": [f.to_public() for f in self.fields],
        }


@dataclass(frozen=True)
class StepUiSchema:
    method_param_key: str | None
    methods: tuple[StepMethodUi, ...] = ()
    common_fields: tuple[UiFieldSpec, ...] = ()
    custom_editor: str | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "method_param_key": self.method_param_key,
            "methods": [m.to_public() for m in self.methods],
            "common_fields": [f.to_public() for f in self.common_fields],
            "custom_editor": self.custom_editor,
        }


@dataclass(frozen=True)
class StepSpec:
    id: str
    label: str
    category: StepCategory
    ui: StepUiSchema
    impl: StepImpl | None = None
    palette_group: PaletteGroup = "Preprocessing"
    description: str = ""
    requires_technique: frozenset[TechniqueFamily] | None = None
    requires_capabilities: frozenset[str] = frozenset()
    excludes_capabilities: frozenset[str] = frozenset()
    validation_rules: tuple[str, ...] = ()

    def applicable(
        self,
        technique_family: str | None,
        capabilities: set[str] | frozenset[str] | None = None,
    ) -> bool:
        caps = frozenset(capabilities or ())
        if self.requires_technique is not None:
            fam = (technique_family or "").strip().lower()
            if fam not in self.requires_technique:
                return False
        if self.requires_capabilities and not self.requires_capabilities.issubset(caps):
            return False
        if self.excludes_capabilities and self.excludes_capabilities.intersection(caps):
            return False
        return True

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "category": self.category,
            "palette_group": self.palette_group,
            "description": self.description,
            "ui": self.ui.to_public(),
            "requires_technique": (
                sorted(self.requires_technique) if self.requires_technique is not None else None
            ),
            "requires_capabilities": sorted(self.requires_capabilities),
            "excludes_capabilities": sorted(self.excludes_capabilities),
            "validation_rules": list(self.validation_rules),
            "has_impl": self.impl is not None,
        }
