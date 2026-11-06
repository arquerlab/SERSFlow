from __future__ import annotations

from typing import Any, Literal

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
    warnings: list[str] = Field(default_factory=list)


class FitFailureItem(BaseModel):
    spectrum_id: str
    step_index: int | None = None
    step_id: str | None = None
    xps_region: str | None = None
    status: Literal["failed", "not_converged"]
    reason: str | None = None


class FitFailureSummary(BaseModel):
    """Per-run fitting outcome counts (K2). ``items`` lists failed / not-converged fits (capped)."""

    n_fits: int = 0
    n_ok: int = 0
    n_failed: int = 0
    n_not_converged: int = 0
    n_not_applicable: int = 0
    items: list[FitFailureItem] = Field(default_factory=list)
    truncated: bool = False


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
    warnings: list[str] = Field(default_factory=list)
    """Run-level warnings, e.g. failed fits (K2). Empty for runs made before this field existed."""
    fit_failures: FitFailureSummary | None = None


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


class FittingPreviewRequest(BaseModel):
    spectrum_ids: list[str] = Field(min_length=1, max_length=50)
    fitting_step_num: int | None = Field(
        default=None,
        description="1-based step number from /fitting-steps (NOT the s{N}_ column prefix).",
    )
    fitting_step_index: int | None = Field(
        default=None,
        description="0-based pipeline step index = the N in observation columns s{N}_... "
        "(alternative to fitting_step_num; give exactly one).",
    )
    return_curve: bool = True


class FitCurveJobCreateRequest(BaseModel):
    fitting_step_num: int | None = Field(
        default=None,
        description="1-based step number from /fitting-steps (NOT the s{N}_ column prefix).",
    )
    fitting_step_index: int | None = Field(
        default=None,
        description="0-based pipeline step index = the N in observation columns s{N}_... "
        "(alternative to fitting_step_num; give exactly one).",
    )
    content: Literal["data_fit_resid", "data_fit_components_resid"] = "data_fit_components_resid"
    format: Literal["csv", "png", "svg"] = "csv"


class SweepAxis(BaseModel):
    component_id: str = Field(min_length=1)
    key: str = Field(min_length=1, description="Parameter key of the component, e.g. fwhm, pos, amp, m.")
    values: list[float] = Field(min_length=1, max_length=200)


class SweepJobCreateRequest(BaseModel):
    """
    Fix parameters of one fitting step at every point of a grid and refit the run's spectra.

    The grid is the Cartesian product of the axes. A swept parameter is fixed (vary=False) at each value;
    parameters linked to it follow. Results: poll/download through the fit-curve job endpoints
    (``sweep_summary.csv`` + ``sweep_points.csv`` in the zip).
    """

    fitting_step_num: int | None = Field(default=None, description="1-based, from /fitting-steps.")
    fitting_step_index: int | None = Field(default=None, description="0-based = N in s{N}_ columns.")
    grid: list[SweepAxis] = Field(min_length=1, max_length=4)
    spectrum_ids: list[str] | None = Field(
        default=None, description="Subset of the run's spectra; default = every spectrum the step applies to."
    )


class MonteCarloJobCreateRequest(BaseModel):
    """
    F2: Monte Carlo parameter uncertainties for one fitting step of a completed run.

    Each spectrum is refitted once (best fit); then ``n_replicates`` noisy copies of the best-fit curve (noise from
    the fit's weighting model: Poisson, relative Poisson, or constant RMSE when unweighted) are refitted. Poll and
    download through the fit-curve job endpoints; ``GET /analysis/monte-carlo-jobs/{job_id}/summary`` returns the
    per-parameter summary as JSON.
    """

    fitting_step_num: int | None = Field(default=None, description="1-based, from /fitting-steps.")
    fitting_step_index: int | None = Field(default=None, description="0-based = N in s{N}_ columns.")
    n_replicates: int = Field(default=100, ge=2, le=2000)
    seed: int = Field(default=0, ge=0, description="Random seed; spectrum k uses seed + k (reproducible).")
    spectrum_ids: list[str] | None = Field(
        default=None, description="Subset of the run's spectra; default = every spectrum the step applies to."
    )


class RobustnessJobCreateRequest(BaseModel):
    """
    Robustness study: a factorial design of analyst choices refitted over a run's spectra, with ANOVA variance shares.

    A FACTOR is one choice (background, fit window, line-shape mix, FWHM constraint, an upstream baseline method...);
    its LEVELS are options, each a list of patches of the fitting step or of an upstream pipeline step (see
    ``core/robustness/patches.py`` and docs/ROBUSTNESS.md). The first level of every factor is the nominal setting.
    Give ``factors`` explicitly or a ``preset`` that proposes them from the run's fitting step (explicit values win).
    ``responses`` are what is compared (area %, positions, widths, group fractions, ratios); ``x_label`` names any
    spectrum label (or numeric metadata) the trend is measured against.
    """

    fitting_step_num: int | None = Field(default=None, description="1-based, from /fitting-steps.")
    fitting_step_index: int | None = Field(default=None, description="0-based = N in s{N}_ columns.")
    preset: str | None = Field(default=None, description="fit_model_choices | baseline_method (proposes factors/responses).")
    preset_options: dict[str, Any] | None = None
    factors: list[dict[str, Any]] | None = Field(default=None, description="[{name, levels:[{name, patches:[...]}]}]")
    responses: list[dict[str, Any]] | None = Field(
        default=None, description="[{name, kind: area_pct|area|param|group_fraction|ratio|difference, ...}]"
    )
    max_cells: int | None = Field(default=None, ge=1, description="Refuse designs above this many cells; null = no cap.")
    interaction_order: int | Literal["all"] | None = Field(default=None, description="1 = main effects; null/'all' = every order.")
    subsample: dict[str, Any] | None = Field(default=None, description="{n, seed}: opt-in random subset of cells (inexact ANOVA).")
    constraints: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Exclusion rules that drop implausible cells before fitting: {exclude_when: {factor: [levels]}} or "
            "{require: \"expr over level values\"}, optional name. Makes the design unbalanced (sequential ANOVA)."
        ),
    )
    n_starts: int = Field(default=1, ge=1, le=50, description="Multi-start per cell; flags degenerate cells.")
    seed: int = Field(default=0, ge=0)
    jitter_frac: float | None = Field(default=None, gt=0)
    cost_tol: float | None = Field(default=None, gt=0)
    resp_tol_rel: float | None = Field(default=None, gt=0)
    resp_tol_abs: float | None = Field(default=None, gt=0)
    x_label: str | None = Field(default=None, description="Label / numeric metadata the trend is measured against.")
    filter: dict[str, Any] | None = Field(
        default=None,
        description="{mode: none|delta_bic_common|delta_bic_native|rmse_ratio, threshold, exclude_degenerate, max_at_bound}",
    )
    noise: dict[str, Any] | None = Field(default=None, description="{n_replicates (0=off), reference_cell, seed}: noise Monte Carlo baseline.")
    reference_cell: str | None = Field(default=None, description="Cell whose trend sign is the reference (default: majority).")
    workers: int | None = Field(default=None, ge=1, le=128, description="Parallel worker processes.")
    allow_large: bool = Field(default=False, description="Bypass the server fit cap (SERSFLOW_ROBUSTNESS_MAX_FITS).")
    spectrum_ids: list[str] | None = None


class RobustnessReanalyseRequest(BaseModel):
    """Recompute a finished study's summary with other responses / filter / interaction order (no refitting)."""

    responses: list[dict[str, Any]] | None = None
    filter: dict[str, Any] | None = None
    interaction_order: int | Literal["all"] | None = None
    x_label: str | None = None
    reference_cell: str | None = None


class ReportJobCreateRequest(BaseModel):
    """
    R1: publication fit report for a completed run (zip with report.html, report.md, report.json, figures/*.png).

    Contents: provenance (file SHA-256, software version + git commit, pipeline hash), acquisition metadata,
    charge correction and applied shifts, processing history, per-region background and components (CasaXPS line
    shape, values ± 1σ, fixed / bounded / linked status), fit statistics, quantification status and a figure.
    """

    spectrum_ids: list[str] | None = Field(default=None, description="Default: every spectrum of the run (server cap).")
    fitting_step_nums: list[int] | None = Field(default=None, description="1-based fitting step numbers; default all.")
    include_figures: bool = True


class StepOutputsJobCreateRequest(BaseModel):
    """Export raw XY plus the output of each selected pipeline step (one CSV per spectrum, zipped)."""

    step_nums: list[int] = Field(min_length=1)
    # None = every spectrum in the analysis cohort.
    spectrum_ids: list[str] | None = None


class FitCurveJobCreateResponse(BaseModel):
    job_id: str
    status: str


class FitCurveJobStatusResponse(BaseModel):
    job_id: str
    run_id: str
    fitting_step_num: int
    content: str
    format: str
    status: str
    progress_done: int
    progress_total: int
    error: str | None = None
    created_at: str
    finished_at: str | None = None
