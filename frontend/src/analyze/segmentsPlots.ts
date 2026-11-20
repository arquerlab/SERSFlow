import type { SegmentsResult, AlignmentSummary } from "./segmentsApi";
import type { CsvRow } from "./export";

export type Fig = { data: unknown[]; layout: Record<string, unknown> };

/** Fixed zone colours (bottom to top); cycles if there are more segments. */
export const ZONE_COLORS = ["#2ca02c", "#ff7f0e", "#1f77b4", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];
export const zoneColor = (i: number) => ZONE_COLORS[i % ZONE_COLORS.length];

function rgba(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return NaN;
  const p = (sorted.length - 1) * q;
  const lo = Math.floor(p);
  const hi = Math.ceil(p);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (p - lo);
}

/** Segmentation cost (contiguous: within-segment SSE; k-means: inertia) and silhouette versus K. */
export function costFigure(r: SegmentsResult): Fig {
  const ks = Object.keys(r.cost_by_k)
    .map(Number)
    .sort((a, b) => a - b);
  const data: unknown[] = [
    { type: "scatter", mode: "lines+markers", x: ks, y: ks.map((k) => r.cost_by_k[String(k)]), name: r.method === "kmeans" ? "inertia" : "within-segment SSE" },
  ];
  const layout: Record<string, unknown> = {
    title: { text: "Cost versus number of segments" },
    xaxis: { title: { text: "K" }, dtick: 1 },
    yaxis: { title: { text: r.method === "kmeans" ? "inertia" : "within-segment SSE" } },
    margin: { t: 40, l: 60, r: 60, b: 45 },
    showlegend: false,
    shapes: [{ type: "line", x0: r.n_segments, x1: r.n_segments, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", color: "#888" } }],
  };
  if (r.silhouette_by_k && Object.keys(r.silhouette_by_k).length) {
    const sk = Object.keys(r.silhouette_by_k)
      .map(Number)
      .sort((a, b) => a - b);
    data.push({ type: "scatter", mode: "lines+markers", x: sk, y: sk.map((k) => r.silhouette_by_k![String(k)]), name: "silhouette", yaxis: "y2" });
    layout.yaxis2 = { title: { text: "silhouette" }, overlaying: "y", side: "right" };
    layout.showlegend = true;
  }
  return { data, layout };
}

/** Median / IQR of one feature per z bin with the zone bands drawn behind it. */
export function profileFigure(
  r: SegmentsResult,
  values: (number | null)[],
  title: string,
  binWidth: number,
  names: string[]
): Fig {
  const bins = new Map<number, number[]>();
  r.z_used.forEach((z, i) => {
    const v = values[i];
    if (v == null || !Number.isFinite(v)) return;
    const b = binWidth > 0 ? Math.round(z / binWidth) * binWidth : z;
    const a = bins.get(b) ?? [];
    a.push(v);
    bins.set(b, a);
  });
  const zs = Array.from(bins.keys()).sort((a, b) => a - b);
  const q = (p: number) => zs.map((z) => quantile(bins.get(z)!.slice().sort((a, b) => a - b), p));
  const med = q(0.5);
  const zmin = r.z_used.length ? Math.min(...r.z_used) : 0;
  const zmax = r.z_used.length ? Math.max(...r.z_used) : 1;
  const edges = [zmin, ...(r.cuts ?? segmentEdgesFromLabels(r)), zmax];
  const shapes = edges.slice(0, -1).map((lo, i) => ({
    type: "rect",
    xref: "x",
    yref: "paper",
    x0: lo,
    x1: edges[i + 1],
    y0: 0,
    y1: 1,
    fillcolor: rgba(zoneColor(i), 0.14),
    line: { width: 0 },
    layer: "below",
  }));
  const annotations = edges.slice(0, -1).map((lo, i) => ({
    x: (lo + edges[i + 1]) / 2,
    xref: "x",
    yref: "paper",
    y: 1,
    yanchor: "bottom",
    showarrow: false,
    text: names[i] ?? `Segment ${i + 1}`,
    font: { size: 11, color: zoneColor(i) },
  }));
  return {
    data: [
      { type: "scatter", mode: "lines", x: zs, y: q(0.75), line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
      { type: "scatter", mode: "lines", x: zs, y: q(0.25), fill: "tonexty", fillcolor: "rgba(128,128,128,0.25)", line: { width: 0 }, name: "IQR", hoverinfo: "skip" },
      { type: "scatter", mode: "lines", x: zs, y: med, line: { width: 2, color: "#222" }, name: "median" },
    ],
    layout: {
      title: { text: title },
      xaxis: { title: { text: r.order_column + (r.alignment ? " (aligned)" : "") } },
      yaxis: { title: { text: "value" } },
      margin: { t: 60, l: 60, r: 20, b: 45 },
      shapes,
      annotations,
      showlegend: false,
    },
  };
}

/** k-means has no cuts: use the extent of each (z-sorted) cluster as band edges (midpoints between neighbours). */
function segmentEdgesFromLabels(r: SegmentsResult): number[] {
  const rows = r.segments.slice().sort((a, b) => a.z_median - b.z_median);
  const out: number[] = [];
  for (let i = 1; i < rows.length; i++) out.push((rows[i - 1].z_max + rows[i].z_min) / 2);
  return out;
}

/** Histogram of the boundaries found independently at each position, with the global cuts drawn on top. */
export function boundaryScatterFigure(r: SegmentsResult): Fig | null {
  const pp = r.per_position_cuts;
  if (!pp || !pp.length || !r.cuts) return null;
  const data = r.cuts.map((_, j) => ({
    type: "histogram",
    x: pp.map((p) => p.cuts[j]).filter((v) => v != null),
    name: `boundary ${j + 1}`,
    marker: { color: zoneColor(j + 1) },
    opacity: 0.65,
  }));
  return {
    data,
    layout: {
      title: { text: "Boundary found independently at each position" },
      barmode: "overlay",
      xaxis: { title: { text: r.order_column + (r.alignment ? " (aligned)" : "") } },
      yaxis: { title: { text: "positions" } },
      margin: { t: 40, l: 55, r: 20, b: 45 },
      shapes: r.cuts.map((c) => ({ type: "line", x0: c, x1: c, yref: "paper", y0: 0, y1: 1, line: { dash: "dash", color: "#222", width: 1 } })),
    },
  };
}

/** Per-position edge and shift (position index on x); the reference position is highlighted. */
export function shiftFigure(a: AlignmentSummary): Fig {
  const pts = a.positions.filter((p) => p.shift != null);
  const lab = pts.map((p) => `(${p.position.join(", ")})`);
  const isRef = (p: number[]) => p.length === a.reference.length && p.every((v, i) => v === a.reference[i]);
  return {
    data: [
      {
        type: "bar",
        x: lab,
        y: pts.map((p) => p.shift),
        marker: { color: pts.map((p) => (isRef(p.position) ? "#d62728" : "#1f77b4")) },
        hovertemplate: "%{x}<br>shift %{y:.2f}<extra></extra>",
      },
    ],
    layout: {
      title: { text: `z shift per position (reference ${a.reference.join(", ")} at ${a.reference_edge_z.toFixed(1)})` },
      xaxis: { title: { text: "position" }, tickangle: -60 },
      yaxis: { title: { text: "shift" } },
      margin: { t: 40, l: 55, r: 20, b: 90 },
      showlegend: false,
    },
  };
}

/** Per-spectrum label table (with the zone name) for CSV export. */
export function labelCsvRows(r: SegmentsResult, names: string[]): CsvRow[] {
  return r.spectrum_ids.map((id, i) => ({
    spectrum_id: id,
    [r.order_column]: r.z_original[i],
    z_used: r.z_used[i],
    segment: r.labels[i] + 1,
    zone: names[r.labels[i]] ?? `Segment ${r.labels[i] + 1}`,
  }));
}

/** Median feature values per segment (rows = features) for CSV export. */
export function signatureCsvRows(r: SegmentsResult, names: string[]): CsvRow[] {
  return r.feature_columns.map((f) => {
    const row: CsvRow = { feature: f };
    r.segments.forEach((s) => {
      row[names[s.segment] ?? `Segment ${s.segment + 1}`] = s.median_features?.[f] ?? null;
    });
    return row;
  });
}
