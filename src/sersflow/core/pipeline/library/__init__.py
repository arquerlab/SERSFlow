"""Processing step library: data-independent transforms + UI + applicability."""

from __future__ import annotations

from sersflow.core.pipeline.library.registry import (
    STEP_LIBRARY,
    get_step,
    list_steps,
    register_step,
)
from sersflow.core.pipeline.library.types import (
    StepCategory,
    StepMethodUi,
    StepSpec,
    StepUiSchema,
    UiFieldSpec,
)

# Side-effect: register builtins
from sersflow.core.pipeline.library import builtins as _builtins  # noqa: F401

__all__ = [
    "STEP_LIBRARY",
    "StepCategory",
    "StepMethodUi",
    "StepSpec",
    "StepUiSchema",
    "UiFieldSpec",
    "get_step",
    "list_steps",
    "register_step",
]
