"""Multivariate analysis of a spectrum matrix (rows = spectra, columns = x channels)."""

from sersflow.core.multivariate.correlation import (
    correlation_matrix,
    reorder_correlation_result,
)
from sersflow.core.multivariate.cos2d import twod_cos
from sersflow.core.multivariate.factorize import run_mcr_als, run_nmf
from sersflow.core.multivariate.preprocess import preprocess_matrix
from sersflow.core.multivariate.rotation import rotate_pca_result, varimax

__all__ = [
    "correlation_matrix",
    "reorder_correlation_result",
    "twod_cos",
    "run_mcr_als",
    "run_nmf",
    "preprocess_matrix",
    "rotate_pca_result",
    "varimax",
]
