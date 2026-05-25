from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import SubsetStrategy


class AnalysisRunCreateRequest(BaseModel):
    """
    Start a batch feature extraction for spectral intensities (and future feature types).

    Provide **either** `session_id` (pipeline + preview subset from session) **or** both `pipeline` and `subset`.
    The session **subset** (random / saved indices) only affects **Prepare** preview plots; feature extraction
    always runs on **every spectrum in the dataset**. The stored `subset_hash` on the run record reflects
    that full-dataset cohort.

    If the pipeline has no enabled `spectral_intensities` step, the server appends a default probe
    (single intensity at 1000 cm⁻¹, column `I_analysis_fallback`) so the run can complete; add your
    own step in Prepare for meaningful features. Feature columns always come from the session pipeline
    last stored via **Prepare → Save pipeline** (not unsaved editor state).

    Rows × columns for PCA: each row is one spectrum (`spectrum_id`), numeric feature columns are `I_*`
    (and optional `peak_pos_cm1_*`, `s{step}_*` when multiple intensity steps exist). See OpenAPI description
    on `/analysis/runs/{run_id}/export` for orientation (samples = rows, features = columns).
    """

    model_config = ConfigDict(populate_by_name=True)

    dataset_id: str = Field(min_length=1)
    session_id: str | None = None
    pipeline_id: str | None = Field(default=None, description="Optional saved pipeline library id (pl_...).")
    pipeline_name: str | None = Field(default=None, description="Optional saved pipeline display name.")
    pipeline: Pipeline | None = None
    subset: SubsetStrategy | None = None
    async_: bool = Field(default=False, alias="async")
    label: str | None = None
    pin: bool = False
    client_job_key: str | None = Field(
        default=None,
        description="Optional idempotency key; duplicate requests return the existing run.",
    )


class AnalysisRunCreateResponse(BaseModel):
    run_id: str
    job_id: str | None = None
    status: str
    message: str | None = None


class AnalysisRunSummary(BaseModel):
    run_id: str
    dataset_id: str
    dataset_name: str | None = None
    session_id: str | None
    pipeline_id: str | None = None
    pipeline_name: str | None = None
    pipeline_hash: str
    pipeline_summary: str | None = None
    subset_hash: str
    status: str
    error: str | None
    created_at: str
    finished_at: str | None
    label: str | None
    pinned: bool
    feature_columns: list[str] | None = None


class AnalysisRunDetailResponse(BaseModel):
    run: AnalysisRunSummary


class AnalysisJobStatusResponse(BaseModel):
    job_id: str
    run_id: str
    status: str
    progress_done: int
    progress_total: int
    error: str | None
    created_at: str
    updated_at: str


class CsvExportContract(BaseModel):
    """Documents the CSV contract for analysis / observation exports (OpenAPI)."""

    encoding: str = "utf-8"
    delimiter: str = ","
    header_row: bool = True
    missing_numeric: str = Field(
        default="empty_string",
        description="Missing or NaN numeric cells are empty in CSV; use Parquet for typed nulls.",
    )
    orientation: str = Field(
        default="rows_are_samples_spectra_columns_are_features",
        description="Each row is one spectrum (`spectrum_id`); numeric columns are model features.",
    )
    notes: str = Field(
        default="",
        description="Wide exports: select numeric columns for sklearn/statsmodels; long exports include a `kind` column.",
    )


class AnalysisExportManifest(BaseModel):
    """JSON returned by `GET /analysis/runs/{run_id}/export/manifest` (and embedded in ZIP bundles)."""

    run_id: str
    dataset_id: str
    pipeline_hash: str
    subset_hash: str
    created_at: str
    finished_at: str | None
    feature_columns: list[str]
    csv_contract: CsvExportContract


class ObservationSchemaResponse(BaseModel):
    """Selectable columns for analysis runs: spectral features plus axis and upload metadata (``meta_*``)."""

    feature_keys: list[str]
    axis_keys: list[str]
    meta_keys: list[str]
