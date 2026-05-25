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
    pipeline: Pipeline | None = None
    up_to_step: str | None = None
    async_: bool = Field(default=False, alias="async")


class MatrixExportResponse(BaseModel):
    matrix_job_id: str
    status: str


class CorrelationRequest(BaseModel):
    analysis_run_id: str
    feature_columns: list[str] | None = None


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


class ExploreJobResponse(BaseModel):
    explore_id: str
    artifact_dir: str
    results: dict[str, Any] = Field(default_factory=dict)
