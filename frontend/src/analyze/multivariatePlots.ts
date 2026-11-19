import type { PlotlyFigure } from "../legacy-wrappers/PlotlyWrapper";
import type { CorrelationMatrixResult, Cos2dResult, FactorResult, MatrixPreprocess } from "./multivariateApi";

const PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"];

function colour(i: number): string {
  return PALETTE[i % PALETTE.length];
}

const AXIS = { automargin: true, showline: true, mirror: true, ticks: "outside" } as const;

/** Drop default-valued preprocessing fields so the request only carries what the user changed. */
export function compactPreprocess(p: MatrixPreprocess): MatrixPreprocess | null {
  const out: MatrixPreprocess = {};
  if (p.crop && Number.isFinite(p.crop[0]) && Number.isFinite(p.crop[1])) out.crop = p.crop;
  const ex = (p.exclude ?? []).filter((w) => Number.isFinite(w[0]) && Number.isFinite(w[1]));
  if (ex.length) out.exclude = ex;
  if ((p.bin ?? 1) > 1) out.bin = p.bin;
  if ((p.smooth_window ?? 0) > 0 || (p.derivative ?? 0) > 0) {
    out.smooth_window = p.smooth_window ?? 0;
    out.smooth_poly = p.smooth_poly ?? 3;
    out.derivative = p.derivative ?? 0;
  }
  if (p.row_norm && p.row_norm !== "none") {
    out.row_norm = p.row_norm;
    if (p.row_norm === "ref_band" && p.ref_band) out.ref_band = p.ref_band;
  }
  if (p.transform && p.transform !== "none") out.transform = p.transform;
  if (p.nonneg && p.nonneg !== "none") out.nonneg = p.nonneg;
  if (p.center && p.center !== "mean") out.center = p.center;
  if (p.scale && p.scale !== "none") out.scale = p.scale;
  return Object.keys(out).length ? out : null;
}

/** Category axis that thins its labels (about 20 visible) instead of hiding all of them. */
function categoryTicks(n: number) {
  const step = Math.max(1, Math.ceil(n / 20));
  return { type: "category", tickmode: "linear", tick0: 0, dtick: step, showticklabels: true } as const;
}

export function buildCorrelationHeatmap(r: CorrelationMatrixResult): PlotlyFigure {
  const isChannels = r.axis === "channels" && Array.isArray(r.x) && r.x.length === r.labels.length;
  const blockNote = (r.block_size ?? 1) > 1 ? `, ${r.block_size} ${isChannels ? "channels" : "samples"} per cell` : "";
  const title = `${isChannels ? "Channel" : "Sample"} ${r.method} correlation${r.reordered ? ` (clustered, ${r.linkage ?? "average"} linkage)` : ""}${blockNote}`;
  const axisTitle = isChannels ? "x (ascending)" : "sample";
  // Channels use true numeric axes (always ascending); samples use a thinned category axis.
  const axisOf = (extra: Record<string, unknown>) =>
    isChannels ? { ...AXIS, type: "linear", ...extra, title: { text: axisTitle } } : { ...AXIS, ...categoryTicks(r.labels.length), tickangle: -60, ...extra, title: { text: axisTitle } };
  return {
    data: [
      {
        type: "heatmap",
        z: r.R,
        x: isChannels ? r.x : r.labels,
        y: isChannels ? r.x : r.labels,
        zmin: -1,
        zmax: 1,
        zmid: 0,
        colorscale: "RdBu",
        reversescale: true,
        colorbar: { title: { text: "r" } },
        hovertemplate: "%{y} / %{x}<br>r = %{z:.3f}<extra></extra>",
      },
    ],
    layout: {
      title: { text: title },
      xaxis: axisOf({}),
      yaxis: axisOf({ autorange: "reversed" }),
      margin: { l: 80, r: 20, t: 50, b: 80 },
    },
  };
}

export function buildComponentSpectra(r: FactorResult, label: string): PlotlyFigure {
  return {
    data: r.components.map((c, i) => ({
      type: "scatter",
      mode: "lines",
      x: r.x_cm1,
      y: c,
      name: `${label}${i + 1}`,
      line: { color: colour(i), width: 1.6 },
    })),
    layout: {
      title: { text: `${label} component spectra` },
      xaxis: { ...AXIS, title: { text: "x (cm⁻¹ / eV)" } },
      yaxis: { ...AXIS, title: { text: "intensity (a.u.)" }, zeroline: true },
      legend: { orientation: "h" },
      margin: { l: 60, r: 20, t: 50, b: 50 },
    },
  };
}

export function buildContributions(r: FactorResult, label: string): PlotlyFigure {
  const idx = r.spectrum_ids.map((_, i) => i);
  const k = r.scores[0]?.length ?? 0;
  return {
    data: Array.from({ length: k }, (_, j) => ({
      type: "scatter",
      mode: "lines+markers",
      x: idx,
      y: r.scores.map((row) => row[j]),
      text: r.spectrum_ids,
      name: `${label}${j + 1}`,
      marker: { size: 4, color: colour(j) },
      line: { color: colour(j), width: 1 },
      hovertemplate: "%{text}<br>%{y:.4g}<extra>" + `${label}${j + 1}` + "</extra>",
    })),
    layout: {
      title: { text: `${label} contributions per spectrum` },
      xaxis: { ...AXIS, title: { text: "spectrum index (matrix order)" } },
      yaxis: { ...AXIS, title: { text: "score / contribution" }, zeroline: true },
      legend: { orientation: "h" },
      margin: { l: 60, r: 20, t: 50, b: 50 },
    },
  };
}

export function buildVarianceBars(r: FactorResult, label: string): PlotlyFigure | null {
  const evr = r.explained_variance_ratio;
  if (!evr || !evr.length) return null;
  return {
    data: [
      {
        type: "bar",
        x: evr.map((_, i) => `${label}${i + 1}`),
        y: evr.map((v) => v * 100),
        marker: { color: evr.map((_, i) => colour(i)) },
      },
    ],
    layout: {
      title: { text: label === "PC" ? "Explained variance" : "Share of signal energy" },
      xaxis: { ...AXIS },
      yaxis: { ...AXIS, title: { text: "%" } },
      margin: { l: 60, r: 20, t: 50, b: 50 },
    },
  };
}

export function buildScoresScatter(r: FactorResult, label: string, xi = 0, yi = 1): PlotlyFigure | null {
  const k = r.scores[0]?.length ?? 0;
  if (k < 2 || xi >= k || yi >= k) return null;
  return {
    data: [
      {
        type: "scatter",
        mode: "markers",
        x: r.scores.map((row) => row[xi]),
        y: r.scores.map((row) => row[yi]),
        text: r.spectrum_ids,
        marker: { size: 6, color: r.scores.map((_, i) => i), colorscale: "Viridis", showscale: true, colorbar: { title: { text: "index" } } },
        hovertemplate: "%{text}<extra></extra>",
      },
    ],
    layout: {
      title: { text: `${label}${xi + 1} vs ${label}${yi + 1}` },
      xaxis: { ...AXIS, title: { text: `${label}${xi + 1}` }, zeroline: true },
      yaxis: { ...AXIS, title: { text: `${label}${yi + 1}` }, zeroline: true },
      margin: { l: 60, r: 20, t: 50, b: 50 },
    },
  };
}

export function buildNmfScan(r: FactorResult): PlotlyFigure | null {
  if (!r.scan || r.scan.length < 2) return null;
  return {
    data: [
      {
        type: "scatter",
        mode: "lines+markers",
        x: r.scan.map((s) => s.k),
        y: r.scan.map((s) => s.lack_of_fit_pct),
        marker: { size: 7 },
        name: "lack of fit",
      },
    ],
    layout: {
      title: { text: "NMF error vs number of components" },
      xaxis: { ...AXIS, title: { text: "k" }, dtick: 1 },
      yaxis: { ...AXIS, title: { text: "‖Y − WH‖ / ‖Y‖ (%)" } },
      margin: { l: 60, r: 20, t: 50, b: 50 },
    },
  };
}

function symmetricRange(z: number[][]): number {
  let m = 0;
  for (const row of z) for (const v of row) if (Number.isFinite(v) && Math.abs(v) > m) m = Math.abs(v);
  return m || 1;
}

export function buildCosMap(r: Cos2dResult, which: "synchronous" | "asynchronous"): PlotlyFigure {
  const z = which === "synchronous" ? r.synchronous : r.asynchronous;
  const m = symmetricRange(z);
  const xs = r.x_map && r.x_map.length === z.length ? r.x_map : r.x_cm1;
  const blockNote = (r.block_size ?? 1) > 1 ? `, ${r.block_size} channels per cell` : "";
  return {
    data: [
      {
        type: "heatmap",
        x: xs,
        y: xs,
        z,
        zmin: -m,
        zmax: m,
        zmid: 0,
        colorscale: "RdBu",
        reversescale: true,
        hovertemplate: "x1 %{x:.1f}, x2 %{y:.1f}<br>%{z:.3g}<extra></extra>",
      },
    ],
    layout: {
      title: { text: `${which === "synchronous" ? "Synchronous Φ" : "Asynchronous Ψ"} (${r.perturbation_label})${blockNote}` },
      xaxis: { ...AXIS, title: { text: "x₁" } },
      yaxis: { ...AXIS, title: { text: "x₂" }, scaleanchor: "x", scaleratio: 1 },
      margin: { l: 60, r: 20, t: 50, b: 50 },
    },
  };
}

export function buildCosAutopower(r: Cos2dResult): PlotlyFigure {
  return {
    data: [
      { type: "scatter", mode: "lines", x: r.x_cm1, y: r.autopower, name: "autopower Φ(x,x)", line: { color: colour(0) } },
      {
        type: "scatter",
        mode: "lines",
        x: r.x_cm1,
        y: r.reference_spectrum,
        name: "reference spectrum",
        yaxis: "y2",
        line: { color: "#888", dash: "dot" },
      },
    ],
    layout: {
      title: { text: "Autopower spectrum" },
      xaxis: { ...AXIS, title: { text: "x" } },
      yaxis: { ...AXIS, title: { text: "Φ(x,x)" } },
      yaxis2: { overlaying: "y", side: "right", title: { text: "reference" }, showgrid: false },
      legend: { orientation: "h" },
      margin: { l: 60, r: 60, t: 50, b: 50 },
    },
  };
}
