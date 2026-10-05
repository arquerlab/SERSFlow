/**
 * Shared Plotly figure builder for fit overlay + residual subplot (65:35).
 * Peaks are drawn on top of background when background components are present.
 *
 * Null/NaN in model curves (outside an internal fit window) must stay gaps —
 * never coerce with ``Number(x) || 0`` or fills drop to zero and wreck the plot.
 */

import { isPeakComponentType, isXpsBgComponentType } from "./fittingUtils";
import type { FitDiagnostics } from "./api";

export type FitPlotComponent = {
  component_id: string;
  component_type: string;
  y_hat?: Array<number | null> | null;
};

export function isBackgroundComponentType(ct: string): boolean {
  const t = ct.trim().toLowerCase();
  return t === "polynomial_background" || isXpsBgComponentType(t);
}

/** Keep finite values; map null/undefined/NaN to NaN so Plotly breaks the line. */
export function gapNumber(v: unknown): number {
  if (v == null) return Number.NaN;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : Number.NaN;
}

export function gapSeries(ys: Array<number | null | undefined> | null | undefined, n?: number): number[] {
  const src = ys ?? [];
  const len = n ?? src.length;
  const out = new Array<number>(len);
  for (let i = 0; i < len; i++) out[i] = gapNumber(src[i]);
  return out;
}

export function sumBackgroundY(
  components: FitPlotComponent[],
  n: number
): { bgSum: number[]; hasBg: boolean } {
  const bgSum = new Array(n).fill(Number.NaN);
  let hasBg = false;
  for (const c of components) {
    if (!isBackgroundComponentType(c.component_type)) continue;
    const y = c.y_hat;
    if (!y || y.length !== n) continue;
    hasBg = true;
    for (let i = 0; i < n; i++) {
      const v = gapNumber(y[i]);
      if (!Number.isFinite(v)) continue;
      bgSum[i] = Number.isFinite(bgSum[i]) ? bgSum[i] + v : v;
    }
  }
  return { bgSum, hasBg };
}

export function peakOnBackground(peak: Array<number | null | undefined>, bgSum: number[]): number[] {
  const n = Math.min(peak.length, bgSum.length);
  const out = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    const p = gapNumber(peak[i]);
    const b = gapNumber(bgSum[i]);
    out[i] = Number.isFinite(p) && Number.isFinite(b) ? p + b : Number.NaN;
  }
  return out;
}

const PEAK_COLORS = ["#e67e22", "#3498db", "#9b59b6", "#1abc9c", "#e74c3c", "#f39c12", "#2ecc71"];

function hexToRgba(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${a})`;
}

function fmtDiag(v: number | null | undefined, digits = 4): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e4 || (Math.abs(v) > 0 && Math.abs(v) < 1e-3)) return v.toExponential(2);
  return v.toFixed(digits);
}

export type BuildFitResidualFigureArgs = {
  x: number[];
  y: number[];
  yHat: Array<number | null>;
  residual: Array<number | null>;
  components: FitPlotComponent[];
  diagnostics?: FitDiagnostics | null;
  title?: string;
  xAxisTitle?: string;
  fillOpacity?: number;
};

export function buildFitResidualFigure(args: BuildFitResidualFigureArgs): {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
} {
  const {
    x,
    y,
    yHat,
    residual,
    components,
    diagnostics,
    title,
    xAxisTitle = "X",
    fillOpacity = 0.25,
  } = args;
  const n = x.length;
  const yHatGap = gapSeries(yHat, n);
  const residualGap = gapSeries(residual, n);
  const { bgSum, hasBg } = sumBackgroundY(components, n);
  const traces: Record<string, unknown>[] = [];

  traces.push({
    type: "scatter",
    mode: "lines",
    x,
    y,
    name: "Data",
    line: { color: "#333", width: 1.5 },
    legendgroup: "data",
  });
  traces.push({
    type: "scatter",
    mode: "lines",
    x,
    y: yHatGap,
    name: "Fit (sum)",
    line: { color: "rgba(231,76,60,0.95)", width: 2 },
    connectgaps: false,
    legendgroup: "fit",
  });

  let peakColorIdx = 0;
  for (const comp of components) {
    const cyRaw = comp.y_hat;
    if (!cyRaw?.length) continue;
    const cy = gapSeries(cyRaw, n);
    const ct = comp.component_type;
    const label = `${ct} [${comp.component_id}]`;
    if (isBackgroundComponentType(ct)) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x,
        y: cy,
        name: label,
        line: { color: "#7f8c8d", width: 1.5, dash: "dot" },
        connectgaps: false,
        legendgroup: "bg",
      });
      continue;
    }
    if (!isPeakComponentType(ct)) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x,
        y: cy,
        name: label,
        line: { color: "#95a5a6", width: 1, dash: "dash" },
        connectgaps: false,
      });
      continue;
    }
    const color = PEAK_COLORS[peakColorIdx % PEAK_COLORS.length] ?? "#888";
    peakColorIdx += 1;
    if (hasBg) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x,
        y: bgSum,
        name: `${label} (bg ref)`,
        line: { width: 0 },
        connectgaps: false,
        showlegend: false,
        hoverinfo: "skip",
        legendgroup: `peak-${comp.component_id}`,
      });
      traces.push({
        type: "scatter",
        mode: "lines",
        x,
        y: peakOnBackground(cy, bgSum),
        name: label,
        line: { color, width: 1.5 },
        connectgaps: false,
        fill: "tonexty",
        fillcolor: hexToRgba(color, fillOpacity),
        legendgroup: `peak-${comp.component_id}`,
      });
    } else {
      traces.push({
        type: "scatter",
        mode: "lines",
        x,
        y: cy,
        name: label,
        line: { color, width: 1.5 },
        connectgaps: false,
        fill: "tozeroy",
        fillcolor: hexToRgba(color, fillOpacity),
      });
    }
  }

  traces.push({
    type: "scatter",
    mode: "markers",
    x,
    y: residualGap,
    name: "Residual",
    marker: { color: "#2c3e50", size: 3, opacity: 0.7 },
    yaxis: "y2",
    showlegend: false,
  });

  const subtitle =
    diagnostics != null
      ? `RMSE=${fmtDiag(diagnostics.rmse)}  R²=${fmtDiag(diagnostics.r2)}  BIC=${fmtDiag(diagnostics.bic)}`
      : undefined;

  // Layout: title (+ GoF) at top; residual below main panel; legend under residual
  // so it never shares the top strip with the title.
  const layout: Record<string, unknown> = {
    title: title
      ? {
          text: subtitle
            ? `${title}<br><span style="font-size:11px;font-weight:normal">${subtitle}</span>`
            : title,
          x: 0.01,
          xanchor: "left",
          y: 0.98,
          yanchor: "top",
        }
      : subtitle
        ? {
            text: subtitle,
            font: { size: 11 },
            x: 0.01,
            xanchor: "left",
            y: 0.98,
            yanchor: "top",
          }
        : undefined,
    xaxis: {
      title: { text: xAxisTitle },
      anchor: "y2",
      domain: [0.0, 1.0],
    },
    yaxis: {
      title: { text: "Intensity" },
      domain: [0.42, 1.0],
      anchor: "x",
    },
    yaxis2: {
      title: { text: "Residual" },
      domain: [0.12, 0.34],
      anchor: "x",
      zeroline: true,
      zerolinewidth: 1,
      zerolinecolor: "#999",
    },
    legend: {
      orientation: "h",
      yanchor: "top",
      y: -0.08,
      xanchor: "center",
      x: 0.5,
      font: { size: 11 },
      bgcolor: "rgba(255,255,255,0.85)",
      borderwidth: 0,
      tracegroupgap: 8,
    },
    margin: {
      l: 64,
      r: 28,
      t: title || subtitle ? 78 : 40,
      b: 96,
    },
    height: 520,
    autosize: true,
    showlegend: true,
  };

  return { data: traces, layout };
}
