from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sersflow.api.schemas.pipeline import Pipeline

PcaScaler = Literal["none", "standard"]


class MatrixExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dataset_id: str | None = Field(default=None, min_length=1)
    analysis_run_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = None
    pipeline_id: str | None = Field(default=None, min_length=1)
    pipeline_name: str | None = Field(default=None, min_length=1)
    pipeline: Pipeline | None = None
    up_to_step: str | None = None
    async_: bool = Field(default=False, alias="async")


class MatrixExportResponse(BaseModel):
    matrix_job_id: str
    status: str


class CorrelationRequest(BaseModel):
    analysis_run_id: str
    feature_columns: list[str] | None = None
    method: Literal["pearson", "spearman"] = "pearson"
    reorder: bool = False
    linkage: Literal["average", "complete", "single", "ward"] = "average"


class VIFRequest(BaseModel):
    analysis_run_id: str
    feature_columns: list[str] = Field(min_length=2)


class PCARequest(BaseModel):
    analysis_run_id: str
    n_components: int | None = Field(default=None, ge=1, le=500)
    feature_columns: list[str] | None = None
    method: Literal["pca", "spca"] = "pca"
    scaler: PcaScaler = "none"
    spca_alpha: float = Field(default=1.0, ge=1e-12, le=1e6)
    spca_ridge_alpha: float = Field(default=1e-5, ge=0.0, le=1e6)


class FPCADiscreteRequest(BaseModel):
    matrix_job_id: str = Field(min_length=1)
    method: Literal["pca", "spca"] = "pca"
    n_components: int | None = Field(default=None, ge=1, le=500)
    scaler: PcaScaler = "none"
    spca_alpha: float = Field(default=1.0, ge=1e-12, le=1e6)
    spca_ridge_alpha: float = Field(default=1e-5, ge=0.0, le=1e6)
    rotation: Literal["none", "varimax"] = "none"
    preprocess: MatrixPreprocess | None = None
    run_async: bool = False  # start in the background; poll GET /explore/runs/{explore_id}


class SpectrumClusterRequest(BaseModel):
    """k-means on PCA scores of row-centered spectrum matrix Y from a completed matrix job."""

    matrix_job_id: str = Field(min_length=1)
    n_clusters: int = Field(default=3, ge=2, le=200)
    seed: int = 0
    n_pc_embedding: int = Field(default=10, ge=1, le=500)


class FPCAFDARequest(BaseModel):
    """Refined functional PCA (scikit-fda); requires optional ``scikit-fda``."""

    matrix_job_id: str = Field(min_length=1)
    n_components: int | None = Field(default=None, ge=1, le=500)


class ClusterRequest(BaseModel):
    analysis_run_id: str
    n_clusters: int = Field(default=3, ge=2, le=200)
    feature_columns: list[str] | None = None
    seed: int = 0


class MatrixPreprocess(BaseModel):
    """Preprocessing applied to the spectrum matrix before the analysis (see core/multivariate/preprocess.py)."""

    crop: list[float] | None = Field(default=None, min_length=2, max_length=2)
    exclude: list[list[float]] | None = None
    bin: int = Field(default=1, ge=1, le=64)
    smooth_window: int = Field(default=0, ge=0, le=201)
    smooth_poly: int = Field(default=3, ge=1, le=7)
    derivative: int = Field(default=0, ge=0, le=2)
    row_norm: Literal["none", "area", "max", "l2", "snv", "ref_band"] = "none"
    ref_band: list[float] | None = Field(default=None, min_length=2, max_length=2)
    transform: Literal["none", "sqrt", "log"] = "none"
    nonneg: Literal["none", "clip", "shift"] = "none"
    center: Literal["none", "mean", "median"] = "mean"
    scale: Literal["none", "autoscale", "pareto", "range", "poisson"] = "none"


class SpectrumCorrelationRequest(BaseModel):
    matrix_job_id: str = Field(min_length=1)
    axis: Literal["channels", "samples"] = "channels"
    method: Literal["pearson", "spearman"] = "pearson"
    reorder: bool = False
    linkage: Literal["average", "complete", "single", "ward"] = "average"
    max_display: int = Field(default=800, ge=100, le=2000)
    run_async: bool = False  # start in the background; poll GET /explore/runs/{explore_id}
    preprocess: MatrixPreprocess | None = None


class SpectrumNMFRequest(BaseModel):
    matrix_job_id: str = Field(min_length=1)
    n_components: int = Field(default=3, ge=1, le=50)
    n_starts: int = Field(default=5, ge=1, le=50)
    scan_k: list[int] | None = None
    seed: int = 0
    alpha_h: float = Field(default=0.0, ge=0.0, le=10.0)  # sparse NMF: L1 on component spectra (relative)
    alpha_w: float = Field(default=0.0, ge=0.0, le=10.0)  # sparse NMF: L1 on contributions (relative)
    l1_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    run_async: bool = False  # start in the background; poll GET /explore/runs/{explore_id}
    preprocess: MatrixPreprocess | None = None


class SpectrumMCRRequest(BaseModel):
    matrix_job_id: str = Field(min_length=1)
    n_components: int = Field(default=3, ge=1, le=50)
    nonneg_conc: bool = True
    nonneg_spec: bool = True
    closure: bool = False
    unimodal_spec: bool = False
    normalise_spec: bool = True
    fixed_spectrum_ids: list[str] | None = None
    solver: Literal["hals", "nnls", "lstsq_clip"] = "hals"
    max_iter: int = Field(default=200, ge=1, le=2000)
    seed: int = 0
    run_async: bool = False  # start in the background; poll GET /explore/runs/{explore_id}
    preprocess: MatrixPreprocess | None = None


class Spectrum2DCOSRequest(BaseModel):
    """2D-COS of a matrix job. Perturbation = sample order unless an observation column is given."""

    matrix_job_id: str = Field(min_length=1)
    perturbation: Literal["sample_order", "observation_column"] = "sample_order"
    analysis_run_id: str | None = None
    perturbation_column: str | None = None
    reference: Literal["mean", "first", "last"] = "mean"
    max_display: int = Field(default=600, ge=100, le=2000)
    run_async: bool = False  # start in the background; poll GET /explore/runs/{explore_id}
    preprocess: MatrixPreprocess | None = None


class ExploreJobResponse(BaseModel):
    explore_id: str
    artifact_dir: str
    results: dict[str, Any] = Field(default_factory=dict)


class DepthAlignParams(BaseModel):
    """Align an ordered axis (e.g. depth z) between map positions using an interface (step) in one feature.

    Per position the half-height crossing of ``feature_column`` along ``order_column`` is located; the shift of
    each position is its edge minus the edge of the reference position (which keeps its z).
    """

    feature_column: str = Field(min_length=1)
    position_columns: list[str] = Field(default_factory=lambda: ["axis_map_x", "axis_map_y"])
    mode: Literal["edge", "argmax"] = "edge"
    direction: Literal["down", "up"] = "down"  # profile falls / rises with increasing z
    smooth: int = Field(default=3, ge=1, le=51)
    plateau_z_max: float | None = None  # default: lowest third of the z range
    plateau_n: int = Field(default=6, ge=1, le=100)
    low_z_range: list[float] | None = Field(default=None, min_length=2, max_length=2)
    search_z_min: float | None = None
    reference: list[float] | None = None  # position coordinates; default = position closest to the centroid


class DepthAlignRequest(DepthAlignParams):
    analysis_run_id: str
    order_column: str = "axis_z"


class SegmentsRequest(BaseModel):
    """Segment spectra along an ordered axis from feature columns of an analysis run (no PCA involved).

    ``method="contiguous"`` = exact dynamic-programming split into contiguous segments along the order axis;
    ``method="kmeans"`` = plain k-means on the same prepared features (clusters numbered by median z).
    """

    analysis_run_id: str
    feature_columns: list[str] = Field(min_length=1)
    order_column: str = "axis_z"
    method: Literal["contiguous", "kmeans"] = "contiguous"
    n_segments: int = Field(default=4, ge=2, le=50)
    k_max: int = Field(default=6, ge=2, le=50)  # scan K = 1..k_max for the cost / silhouette curve
    bin_width: float = Field(default=5.0, ge=0.0)  # contiguous: z bin width (0 = every distinct z)
    winsor_pct: float | None = Field(default=99.0, gt=50.0, le=100.0)
    robust_clip: float | None = Field(default=5.0, gt=0.0)
    standardize: bool = True
    seed: int = 0
    n_init: int = Field(default=50, ge=1, le=500)
    per_position_check: bool = True  # contiguous: independent split per position (boundary scatter)
    position_columns: list[str] = Field(default_factory=lambda: ["axis_map_x", "axis_map_y"])
    align: DepthAlignParams | None = None  # align z first (the aligned z is then used)
    zone_names: list[str] | None = None  # optional labels, bottom to top (increasing z)
