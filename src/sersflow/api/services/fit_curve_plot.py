"""Matplotlib 65:35 fit + residual plots for fit-curve export jobs."""

from __future__ import annotations

import io
from typing import Any, Sequence

import numpy as np


def _component_label(comp: dict[str, Any]) -> str:
    """Peak name (component_id) as used in feature columns; falls back to the type."""
    return str(comp.get("component_id") or "").strip() or str(comp.get("component_type") or "")


def _is_background(component_type: str) -> bool:
    t = str(component_type or "").strip().lower()
    return t == "polynomial_background" or t.endswith("_bg")


def _is_peak(component_type: str) -> bool:
    from sersflow.core.preprocess.fitting_specs import PEAK_COMPONENT_TYPES

    return str(component_type or "").strip().lower() in PEAK_COMPONENT_TYPES


def render_fit_residual_figure(
    *,
    x: Sequence[float],
    y: Sequence[float],
    y_hat: Sequence[float],
    residual: Sequence[float],
    components: Sequence[dict[str, Any]],
    title: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    include_components: bool = True,
    table_rows: Sequence[Sequence[str]] | None = None,
    x_label: str | None = None,
    invert_x: bool = False,
) -> Any:
    """
    Fit (top, 65 %) and residual (bottom) figure.

    ``table_rows`` (header first) draws a component table on the plot (R1 report); ``invert_x`` shows a
    binding-energy axis decreasing to the right, as is usual for XPS.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xf = np.asarray(x, dtype=float)
    yf = np.asarray(y, dtype=float)
    yh = np.asarray(y_hat, dtype=float)
    rr = np.asarray(residual, dtype=float)

    fig, (ax_top, ax_bot) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(8, 5.5),
        gridspec_kw={"height_ratios": [65, 35], "hspace": 0.08},
    )
    ax_top.plot(xf, yf, color="#333333", lw=1.2, label="Data")
    ax_top.plot(xf, yh, color="#e74c3c", lw=1.6, label="Fit (sum)")

    n = xf.size
    bg_sum = np.full(n, np.nan, dtype=float)
    has_bg = False
    if include_components:
        for comp in components:
            ct = str(comp.get("component_type") or "")
            cy = comp.get("y_hat")
            if cy is None:
                continue
            arr = np.asarray(cy, dtype=float)
            if arr.shape != xf.shape:
                continue
            if _is_background(ct):
                has_bg = True
                finite = np.isfinite(arr)
                if not np.any(np.isfinite(bg_sum)):
                    bg_sum = arr.copy()
                else:
                    both = np.isfinite(bg_sum) & finite
                    bg_sum = np.where(both, bg_sum + arr, np.where(finite, arr, bg_sum))
                ax_top.plot(xf, arr, color="#7f8c8d", lw=1.0, ls=":", label=_component_label(comp))

        for comp in components:
            ct = str(comp.get("component_type") or "")
            if not _is_peak(ct):
                continue
            cy = comp.get("y_hat")
            if cy is None:
                continue
            arr = np.asarray(cy, dtype=float)
            if arr.shape != xf.shape:
                continue
            if has_bg:
                plot_y = np.where(np.isfinite(arr) & np.isfinite(bg_sum), bg_sum + arr, np.nan)
                label = _component_label(comp)
                ax_top.fill_between(xf, bg_sum, plot_y, alpha=0.25, label=label, where=np.isfinite(plot_y))
                ax_top.plot(xf, plot_y, lw=1.0)
            else:
                plot_y = arr
                label = _component_label(comp)
                ax_top.fill_between(xf, 0, plot_y, alpha=0.25, label=label, where=np.isfinite(plot_y))
                ax_top.plot(xf, plot_y, lw=1.0)

    ax_top.set_ylabel("Intensity")
    ax_top.legend(loc="upper right", fontsize=7, frameon=False)
    if title or diagnostics:
        parts = []
        if title:
            parts.append(str(title))
        if diagnostics:
            rmse = diagnostics.get("rmse")
            r2 = diagnostics.get("r2")
            bic = diagnostics.get("bic")
            parts.append(f"RMSE={rmse}  R²={r2}  BIC={bic}")
        ax_top.set_title("\n".join(parts), fontsize=10)

    ax_bot.scatter(xf, rr, s=6, c="#2c3e50", alpha=0.7)
    ax_bot.axhline(0.0, color="#999", lw=0.8)
    ax_bot.set_ylabel("Residual")
    ax_bot.set_xlabel(x_label or "X")
    if invert_x:
        ax_top.invert_xaxis()  # shared x: both panels follow
    if table_rows and len(table_rows) > 1:
        tbl = ax_top.table(
            cellText=[list(r) for r in table_rows[1:]],
            colLabels=list(table_rows[0]),
            loc="upper left",
            cellLoc="left",
            colLoc="left",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(6.5)
        tbl.auto_set_column_width(col=list(range(len(table_rows[0]))))
        for cell in tbl.get_celld().values():
            cell.set_alpha(0.85)
            cell.set_linewidth(0.3)
        ymin, ymax = ax_top.get_ylim()
        ax_top.set_ylim(ymin, ymax + 0.07 * len(table_rows) * (ymax - ymin) * 1.6)
    return fig


def render_fit_residual_png(**kwargs: Any) -> bytes:
    fig = render_fit_residual_figure(**kwargs)
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        return buf.getvalue()
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def render_fit_residual_svg(**kwargs: Any) -> bytes:
    fig = render_fit_residual_figure(**kwargs)
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="svg", bbox_inches="tight")
        return buf.getvalue()
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)
