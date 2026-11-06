"""Render the R1 fit report dict as self-contained HTML (figures embedded) and as Markdown (figures as files)."""

from __future__ import annotations

import base64
import html
import json
import math
from typing import Any

from sersflow.core.report.fit_report_model import status_text


def _num(v: Any, se: Any = None) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(x):
        return "-"
    try:
        e = float(se)
    except (TypeError, ValueError):
        e = float("nan")
    if math.isfinite(e) and e > 1e-9 * max(abs(x), 1.0):
        d = max(0, min(6, 1 - int(math.floor(math.log10(e)))))
        return f"{x:.{d}f} ± {e:.{d}f}"
    return f"{x:.4g}" if abs(x) >= 1e5 or (x != 0 and abs(x) < 1e-3) else f"{x:.3f}".rstrip("0").rstrip(".")


def _kv(d: dict[str, Any]) -> list[tuple[str, str]]:
    return [(k, "-" if v is None else (json.dumps(v) if isinstance(v, (dict, list)) else str(v))) for k, v in d.items()]


def _sections(report: dict[str, Any]) -> list[tuple[str, Any]]:
    """Ordered (title, payload) list shared by both renderers."""
    return [
        ("Provenance", report),
        ("Processing history", report.get("processing_history") or []),
        ("Charge correction", report.get("charge_correction") or {}),
        ("Quantification", report.get("quantification") or {}),
        ("Spectra and fits", report.get("spectra") or []),
        ("Report checklist", report.get("checklist") or []),
    ]


def _bg_text(bg: dict[str, Any]) -> str:
    """Background component: line shape, options (Av Width, offsets, SB source) and parameters with status."""
    opts = bg.get("options") or {}
    opt_txt = ", ".join(f"{k}={v}" for k, v in opts.items())
    params = "; ".join(f"{k} = {_num(p.get('value'), p.get('stderr'))} ({status_text(p)})" for k, p in (bg.get("params") or {}).items())
    return f"{bg.get('lineshape')}{' [' + opt_txt + ']' if opt_txt else ''} — {params}"


def _component_header() -> list[str]:
    return ["Peak", "Line shape", "Position (eV)", "FWHM (eV)", "Height", "Area", "%Area", "Constraints"]


def _component_cells(c: dict[str, Any]) -> list[str]:
    cons = []
    for k, p in (c.get("params") or {}).items():
        st = status_text(p)
        cons.append(f"{k}: {st}")
    return [
        str(c.get("component_id")),
        str(c.get("lineshape")),
        _num(c.get("position"), c.get("position_stderr")),
        _num(c.get("fwhm"), c.get("fwhm_stderr")),
        _num(c.get("height"), c.get("height_stderr")),
        _num(c.get("area"), c.get("area_stderr")),
        _num(c.get("area_pct"), c.get("area_pct_stderr")),
        "; ".join(cons),
    ]


def _stat_rows(st: dict[str, Any]) -> list[tuple[str, str]]:
    labels = [
        ("optimiser", "Optimiser"),
        ("n_points", "N points"),
        ("n_vary", "Free parameters"),
        ("weighting", "Weighting"),
        ("chi2", "chi2"),
        ("redchi", "Reduced chi2"),
        ("chi2_reduced_weighted", "Reduced chi2 (absolute Poisson)"),
        ("residual_std_normalised", "Normalised residual STD"),
        ("poisson_gain", "Poisson gain g"),
        ("rmse", "RMSE"),
        ("r2", "R²"),
        ("bic", "BIC"),
        ("n_at_bound", "Parameters at a bound"),
        ("success", "Converged"),
    ]
    out = []
    for k, lab in labels:
        v = st.get(k)
        if v is None:
            continue
        if k == "weighting":
            v = {0: "none", 1: "Poisson", 2: "relative Poisson"}.get(v, v) if isinstance(v, (int, float)) else v
            if st.get("weighting_note"):
                v = f"{v} ({st['weighting_note']})"
        elif isinstance(v, float):
            v = _num(v)
        out.append((lab, str(v)))
    return out


def _acq_rows(a: dict[str, Any]) -> list[tuple[str, str]]:
    if not a.get("available"):
        return [("Acquisition", a.get("note") or "not available")]
    labels = [
        ("technique", "Technique"),
        ("source_label", "Source"),
        ("excitation_energy_eV", "Excitation energy (eV)"),
        ("source_analyser_angle_deg", "Source-analyser angle (deg)"),
        ("analyser_mode", "Analyser mode"),
        ("pass_energy_eV", "Pass energy (eV)"),
        ("x_step_eV", "Step (eV)"),
        ("dwell_time_s", "Dwell (s)"),
        ("n_scans", "Scans"),
        ("y_unit", "Ordinate"),
        ("max_channel_counts", "Counts at max channel"),
        ("max_channel_cps", "Count rate at max channel (cps)"),
    ]
    return [(lab, "-" if a.get(k) is None else (_num(a[k]) if isinstance(a.get(k), float) else str(a[k]))) for k, lab in labels]


# ------------------------------------------------------------------------------------------------ HTML


_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:24px auto;max-width:1100px;padding:0 16px;color:#1d2330;background:#fff}
h1{font-size:22px}h2{font-size:18px;border-bottom:1px solid #ccd;padding-bottom:4px;margin-top:28px}h3{font-size:15px;margin:18px 0 6px}
table{border-collapse:collapse;margin:6px 0 12px;font-size:12.5px}td,th{border:1px solid #d5d9e2;padding:3px 7px;text-align:left;vertical-align:top}
th{background:#f1f3f8}code{font-size:12px}.muted{color:#667}.warn{background:#fff6e0;border:1px solid #f0c36d;padding:6px 10px}
.ok{color:#1b7f3b}.miss{color:#b3261e}img{max-width:100%;border:1px solid #e3e6ee}
@media print{h2{page-break-before:auto}.spectrum{page-break-inside:avoid}}
"""


def _h_table(header: list[str] | None, rows: list[list[str]]) -> str:
    out = ["<table>"]
    if header:
        out.append("<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in header) + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def render_html(report: dict[str, Any], figures: dict[str, bytes] | None = None) -> str:
    figures = figures or {}
    run = report.get("run") or {}
    sw = report.get("software") or {}
    e = html.escape
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Fit report {e(str(run.get('run_id')))}</title><style>{_CSS}</style></head><body>",
        f"<h1>XPS fit report</h1><p class='muted'>Run <code>{e(str(run.get('run_id')))}</code>"
        f"{' (' + e(str(run.get('label'))) + ')' if run.get('label') else ''} · generated {e(str(report.get('generated_at')))}</p>",
        "<h2>Provenance</h2>",
        _h_table(
            None,
            [
                ["Software", f"{sw.get('name')} {sw.get('version')}"],
                ["Git commit", str(sw.get("git_commit") or "unknown")],
                ["Dataset", f"{run.get('dataset_name') or ''} ({run.get('dataset_id')})"],
                ["Pipeline", f"{run.get('pipeline_name') or '-'} · hash {run.get('pipeline_hash')}"],
                ["Subset hash", str(run.get("subset_hash"))],
                ["Run created / finished", f"{run.get('created_at')} / {run.get('finished_at')}"],
                ["Technique", str(run.get("technique_family"))],
                ["Report schema", str(report.get("schema"))],
            ],
        ),
        "<h2>Processing history</h2>",
        _h_table(
            ["#", "Step", "Enabled", "Parameters"],
            [
                [
                    str(s.get("step_num")),
                    str(s.get("name")),
                    "yes" if s.get("enabled") else "no",
                    json.dumps(s.get("summary") or s.get("params"), default=str)[:900],
                ]
                for s in report.get("processing_history") or []
            ],
        ),
        "<h2>Charge correction</h2>",
    ]
    cc = report.get("charge_correction") or {}
    if cc.get("steps"):
        parts.append(
            _h_table(
                ["Step", "Method", "Reference", "Note"],
                [
                    [str(s.get("step_num")), str(s.get("method")), json.dumps(s.get("reference"), default=str)[:600], str(s.get("shift_error") or "")]
                    for s in cc["steps"]
                ],
            )
        )
        parts.append("<p class='muted'>The applied shift per spectrum is listed with each spectrum below.</p>")
    else:
        parts.append(f"<p>{e(str(cc.get('note') or 'none'))}</p>")
    q = report.get("quantification") or {}
    parts.append(f"<h2>Quantification</h2><p class='warn'>{e(str(q.get('reason') or q.get('status')))}</p>")
    parts.append("<h2>Spectra and fits</h2>")
    for s in report.get("spectra") or []:
        f = s.get("file") or {}
        parts.append(f"<div class='spectrum'><h3>{e(str(s.get('spectrum_id')))}</h3>")
        info = [
            ["File", f"{f.get('relative_path')} (block {f.get('record_index')})"],
            ["SHA-256", str(f.get("sha256"))],
            *[[k, str(v)] for k, v in (s.get("labels") or {}).items()],
            *[[k, v] for k, v in _acq_rows(s.get("acquisition") or {})],
        ]
        shifts = s.get("charge_shift_eV") or {}
        if shifts:
            info.append(["Charge-correction shift (eV)", ", ".join(f"step {k}: {_num(v)}" for k, v in shifts.items())])
        parts.append(_h_table(None, info))
        for fit in s.get("fits") or []:
            title = f"Fitting step {fit.get('fitting_step_num')}" + (f" · {fit.get('xps_region')}" if fit.get("xps_region") else "")
            parts.append(f"<h3>{e(title)}</h3>")
            if fit.get("error"):
                parts.append(f"<p class='warn'>Fit not available: {e(str(fit['error']))}</p>")
                continue
            bgs = fit.get("backgrounds") or ([fit["background"]] if fit.get("background") else [])
            win = fit.get("fit_window") or [None, None]
            parts.append(
                "<p>Background: "
                + (e(" + ".join(_bg_text(b) for b in bgs)) if bgs else "none (no active background component)")
                + f" · fit window: {e(str(win[0]))} – {e(str(win[1]))} eV"
                + (f" · recipe: {e(', '.join(fit.get('recipe_ids') or []))}" if fit.get("recipe_ids") else "")
                + "</p>"
            )
            parts.append(_h_table(_component_header(), [_component_cells(c) for c in fit.get("components") or []]))
            parts.append(_h_table(["Fit statistic", "Value"], [list(r) for r in _stat_rows(fit.get("statistics") or {})]))
            fig = fit.get("figure")
            if fig and fig in figures:
                b64 = base64.b64encode(figures[fig]).decode("ascii")
                parts.append(f"<img alt='fit {e(str(s.get('spectrum_id')))}' src='data:image/png;base64,{b64}'>")
        parts.append("</div>")
    parts.append("<h2>Report checklist</h2>")
    parts.append(
        "<table><tr><th>Item</th><th>Present</th><th>Note</th></tr>"
        + "".join(
            f"<tr><td>{e(c['label'])}</td><td class='{'ok' if c['present'] else 'miss'}'>{'yes' if c['present'] else 'no'}</td><td>{e(str(c.get('note') or ''))}</td></tr>"
            for c in report.get("checklist") or []
        )
        + "</table>"
    )
    parts.append("<p class='muted'>± = 1σ from the fit covariance scaled by the reduced χ² (F2). Monte Carlo uncertainties, when run, are in the Monte Carlo job export.</p>")
    parts.append("</body></html>")
    return "".join(parts)


# -------------------------------------------------------------------------------------------- Markdown


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    def cell(x: Any) -> str:
        return str(x).replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(cell(h) for h in header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(report: dict[str, Any]) -> str:
    run = report.get("run") or {}
    sw = report.get("software") or {}
    lines = [
        "# XPS fit report",
        "",
        f"Run `{run.get('run_id')}`{' (' + str(run.get('label')) + ')' if run.get('label') else ''}, generated {report.get('generated_at')}.",
        "",
        "## Provenance",
        "",
        _md_table(
            ["Item", "Value"],
            [
                ["Software", f"{sw.get('name')} {sw.get('version')}"],
                ["Git commit", str(sw.get("git_commit") or "unknown")],
                ["Dataset", f"{run.get('dataset_name') or ''} ({run.get('dataset_id')})"],
                ["Pipeline hash", str(run.get("pipeline_hash"))],
                ["Technique", str(run.get("technique_family"))],
            ],
        ),
        "",
        "## Processing history",
        "",
        _md_table(
            ["#", "Step", "Enabled", "Parameters"],
            [
                [str(s.get("step_num")), str(s.get("name")), "yes" if s.get("enabled") else "no", json.dumps(s.get("summary") or s.get("params"), default=str)[:400]]
                for s in report.get("processing_history") or []
            ],
        ),
        "",
        "## Charge correction",
        "",
    ]
    cc = report.get("charge_correction") or {}
    if cc.get("steps"):
        lines.append(
            _md_table(
                ["Step", "Method", "Reference"],
                [[str(s.get("step_num")), str(s.get("method")), json.dumps(s.get("reference"), default=str)[:300]] for s in cc["steps"]],
            )
        )
    else:
        lines.append(str(cc.get("note") or "none"))
    q = report.get("quantification") or {}
    lines += ["", "## Quantification", "", f"> {q.get('reason') or q.get('status')}", "", "## Spectra and fits", ""]
    for s in report.get("spectra") or []:
        f = s.get("file") or {}
        lines += [f"### {s.get('spectrum_id')}", ""]
        rows = [
            ["File", f"{f.get('relative_path')} (block {f.get('record_index')})"],
            ["SHA-256", str(f.get("sha256"))],
            *[[k, str(v)] for k, v in (s.get("labels") or {}).items()],
            *[[k, v] for k, v in _acq_rows(s.get("acquisition") or {})],
        ]
        shifts = s.get("charge_shift_eV") or {}
        if shifts:
            rows.append(["Charge-correction shift (eV)", ", ".join(f"step {k}: {_num(v)}" for k, v in shifts.items())])
        lines += [_md_table(["Item", "Value"], rows), ""]
        for fit in s.get("fits") or []:
            lines += [f"#### Fitting step {fit.get('fitting_step_num')}" + (f" · {fit.get('xps_region')}" if fit.get("xps_region") else ""), ""]
            if fit.get("error"):
                lines += [f"Fit not available: {fit['error']}", ""]
                continue
            bgs = fit.get("backgrounds") or ([fit["background"]] if fit.get("background") else [])
            win = fit.get("fit_window") or [None, None]
            lines.append(
                "Background: "
                + (" + ".join(_bg_text(b) for b in bgs) if bgs else "none")
                + f"; fit window {win[0]} – {win[1]} eV."
            )
            lines += ["", _md_table(_component_header(), [_component_cells(c) for c in fit.get("components") or []]), ""]
            lines += [_md_table(["Fit statistic", "Value"], [list(r) for r in _stat_rows(fit.get("statistics") or {})]), ""]
            if fit.get("figure"):
                lines += [f"![fit {s.get('spectrum_id')}]({fit['figure']})", ""]
    lines += [
        "## Report checklist",
        "",
        _md_table(["Item", "Present", "Note"], [[c["label"], "yes" if c["present"] else "no", str(c.get("note") or "")] for c in report.get("checklist") or []]),
        "",
        "± = 1σ from the fit covariance scaled by the reduced χ² (F2).",
        "",
    ]
    return "\n".join(lines)
