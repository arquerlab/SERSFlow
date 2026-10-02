"""Mutable registry for processing steps."""

from __future__ import annotations

from typing import Iterable

from sersflow.core.pipeline.library.types import StepSpec

STEP_LIBRARY: dict[str, StepSpec] = {}


def register_step(spec: StepSpec) -> StepSpec:
    STEP_LIBRARY[spec.id] = spec
    return spec


def get_step(step_id: str) -> StepSpec | None:
    return STEP_LIBRARY.get(step_id)


def list_steps(
    *,
    technique_family: str | None = None,
    capabilities: Iterable[str] | None = None,
) -> list[StepSpec]:
    caps = frozenset(capabilities or ())
    out = [
        s
        for s in STEP_LIBRARY.values()
        if s.applicable(technique_family, caps)
    ]
    return sorted(out, key=lambda s: s.id)
