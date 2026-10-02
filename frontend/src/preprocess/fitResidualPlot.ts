/**
 * Shared Plotly figure builder for fit overlay + residual subplot (65:35).
 * Peaks are drawn on top of background when background components are present.
 */

import { isPeakComponentType, isXpsBgComponentType } from "./fittingUtils";
import type { FitDiagnostics } from "./api";

export type FitPlotComponent = {
  component_id: string;
  component_type: string;
  y_hat?: number[] | null;
};

export function isBackgroundComponentType(ct: string): boolean {
  const t = ct.trim().toLowerCase();
  return t === "polynomial_background" || isXpsBgComponentType(t);
}

export function sumBackgroundY(
  components: FitPlotComponent[],
  n: number
): { bgSum: number[]; hasBg: boolean } {
  const bgSum = new Array(n).fill(0);
  let hasBg = false;
  for (const c of components) {
    if (!isBackgroundComponentType(c.component_type)) continue;
    const y = c.y_hat;
    if (!y || y.length !== n) continue;
    hasBg = true;
    for (let i = 0; i < n; i++) bgSum[i] += Number(y[i]) || 0;
  }
  return { bgSum, hasBg };
}

export function peakOnBackground(peak: number[], bgSum: number[]): number[] {
  const n = Math.min(peak.length, bgSum.length);
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = (Number(peak[i]) || 0) + (Number(bgSum[i]) || 0);
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
  yHat: number[];
  residual: number[];
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
    y: yHat,
    name: "Fit (sum)",
    line: { color: "rgba(231,76,60,0.95)", width: 2 },
    legendgroup: "fit",
  });

  let peakColorIdx = 0;
  for (const comp of components) {
    const cy = comp.y_hat;
    if (!cy?.length) continue;
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
        fill: "tozeroy",
        fillcolor: hexToRgba(color, fillOpacity),
      });
    }
  }

  traces.push({
    type: "scatter",
    mode: "markers",
    x,
    y: residual,
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
