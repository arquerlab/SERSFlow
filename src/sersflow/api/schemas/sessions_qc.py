from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionQcPreviewRequest(BaseModel):
    scope: Literal["subset", "all"] = "subset"
    step_id: str = Field(min_length=1, description="Pipeline step_id to preview (the QC step).")
    step_params: dict[str, Any] = Field(default_factory=dict, description="Temporary params override for this step only.")


class SessionQcScoreRow(BaseModel):
    spectrum_id: str
    score: float | None = None
    flagged: bool


class SessionQcPreviewHistogram(BaseModel):
    bins: list[float] = Field(default_factory=list, description="Bin edges (length = n_bins+1).")
    counts: list[int] = Field(default_factory=list, description="Counts per bin (length = n_bins).")
    nonfinite: int = 0


class SessionQcPreviewSummary(BaseModel):
    total: int
    flagged_count: int
    flagged_pct: float


class SessionQcPreviewResponse(BaseModel):
    step_id: str
    step_name: str
    summary: SessionQcPreviewSummary
    histogram: SessionQcPreviewHistogram
    threshold: float
    direction: Literal["below", "above"]
    scores: list[SessionQcScoreRow] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

