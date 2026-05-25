from __future__ import annotations

import os
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np

RAMAN_SHIFT_AXIS_LABEL = "Raman shift (cm⁻¹)"


def plot_scree(explained_variance_ratio: list[float], out_path: str, *, title: str = "Scree") -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    ev = np.asarray(explained_variance_ratio, dtype=float)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(np.arange(1, len(ev) + 1), ev, color="steelblue")
    ax.set_xlabel("Component")
    ax.set_ylabel("Explained variance ratio")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_scores_scatter(
    scores: list[list[float]],
    out_path: str,
    *,
    x_comp: int = 0,
    y_comp: int = 1,
) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    s = np.asarray(scores, dtype=float)
    if s.ndim != 2 or s.shape[1] < 2:
        return
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(s[:, x_comp], s[:, y_comp], s=8, alpha=0.6)
    ax.set_xlabel(f"PC{x_comp + 1}")
    ax.set_ylabel(f"PC{y_comp + 1}")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_loading_curve(x: list[float], loading: list[float], out_path: str, *, title: str = "Loading") -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(np.asarray(x, dtype=float), np.asarray(loading, dtype=float), lw=1.0)
    ax.set_xlabel(RAMAN_SHIFT_AXIS_LABEL)
    ax.set_ylabel("Loading")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def write_pca_plots(artifact_dir: str, pca_result: dict[str, Any]) -> dict[str, str]:
    """Returns map plot_name -> relative path."""
    out: dict[str, str] = {}
    ev = pca_result.get("explained_variance_ratio")
    if isinstance(ev, list) and ev:
        p = os.path.join(artifact_dir, "scree.png")
        plot_scree(ev, p)
        out["scree"] = p
    scores = pca_result.get("scores")
    if isinstance(scores, list) and scores and len(scores[0]) >= 2:
        p = os.path.join(artifact_dir, "scores_pc1_pc2.png")
        plot_scores_scatter(scores, p)
        out["scores_pc1_pc2"] = p
    return out
