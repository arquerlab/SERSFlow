"""Make payloads strictly JSON-serialisable (NaN / +-inf are not valid JSON)."""

from __future__ import annotations

import math
from typing import Any


def sanitize_floats(obj: Any) -> Any:
    """
    Recursively replace non-finite floats with ``None``.

    FastAPI endpoints declared with ``response_model=None`` return plain dicts that Starlette renders with
    ``allow_nan=False``: a single NaN (e.g. a residual outside the fit window) turns the response into an
    HTTP 500. Pydantic response models already do this conversion; plain-dict endpoints need this helper.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_floats(v) for v in obj]
    return obj
