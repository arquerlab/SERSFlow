import type { PlotlyFigure } from "../legacy-wrappers/PlotlyWrapper";

export type ParamPlotStyle = "scatter" | "line" | "errorbars" | "errorbars_line" | "boxplot";

export const PARAM_PLOT_STYLES: { value: ParamPlotStyle; label: string }[] = [
  { value: "scatter", label: "Scatter" },
  { value: "line", label: "Line (sorted by X, no error)" },
  { value: "errorbars", label: "Mean ± error bars (group by X)" },
  { value: "errorbars_line", label: "Line + error bars (group by X)" },
  { value: "boxplot", label: "Boxplot (group by X)" },
];

export type ParamPlotConfig = {
  id: string;
  style: ParamPlotStyle;
  x: string;
  /** One or more Y columns; empty strings are unset rows in the editor. */
  ys: string[];
  color: string;
  xErr: string;
  /** Only used when exactly one Y column is selected. */
  yErr: string;
};

let plotSeq = 0;

export function newParamPlotConfig(): ParamPlotConfig {
  plotSeq += 1;
  return { id: `plot_${Date.now().toString(36)}_${plotSeq}`, style: "scatter", x: "", ys: [""], color: "", xErr: "", yErr: "" };
}

export function selectedYs(cfg: ParamPlotConfig): string[] {
  return Array.from(new Set(cfg.ys.filter(Boolean)));
}

/** Columns to fetch from the observation table for this plot. */
export function paramPlotColumns(cfg: ParamPlotConfig): string[] {
  const ys = selectedYs(cfg);
  const yErr = ys.length === 1 ? cfg.yErr : "";
  return Array.from(new Set([cfg.x, ...ys, cfg.color, cfg.xErr, yErr].filter(Boolean)));
}

export function cellToNumber(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "boolean") return null;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function meanStd(values: number[]): { mean: number; std: number } {
  if (!values.length) return { mean: NaN, std: NaN };
  const n = values.length;
  const mean = values.reduce((a, b) => a + b, 0) / n;
  if (n < 2) return { mean, std: 0 };
  let acc = 0;
  for (const v of values) acc += (v - mean) ** 2;
  // sample std
  const std = Math.sqrt(acc / (n - 1));
  return { mean, std };
}

export function stableNumberKey(v: number, decimals = 6): string {
  if (!Number.isFinite(v)) return "NaN";
  // Avoid 0.30000000000000004 style jitter; keep integers compact.
  const r = Math.round(v);
  if (Math.abs(v - r) < 1e-12) return String(r);
  return v.toFixed(decimals);
}

type Point = {
  spectrum_id: string;
  x: number;
  y: number;
  color: number | null;
  x_err: number | null;
  y_err: number | null;
};

export type ParamPlotResult = {
  figure: PlotlyFigure;
  /** Header + rows for "Export CSV" (one row per spectrum with a finite X and at least one finite Y). */
  csvHeader: string[];
  csvRows: (string | number | null)[][];
};

const SYMBOLS = ["circle", "square", "diamond", "triangle-up", "cross", "x", "star", "triangle-down"];

function colorBucket(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "—";
  return stableNumberKey(v, 6);
}

function sortByX<T extends { x: number }>(pts: T[]): T[] {
  return [...pts].sort((a, b) => a.x - b.x);
}

/** Group by X (and a discrete color bucket) into mean ± error series. */
function aggregatedTraces(
  pts: Point[],
  cfg: ParamPlotConfig,
  useColorGrouping: boolean,
  namePrefix: string | undefined
): Record<string, unknown>[] {
  type Group = { xVals: number[]; yVals: number[]; xErrVals: number[]; yErrVals: number[] };
  const groups = new Map<string, Group>();
  for (const r of pts) {
    const xKey = stableNumberKey(r.x, 6);
    const key = useColorGrouping ? `${colorBucket(r.color)}||${xKey}` : xKey;
    const g = groups.get(key) ?? { xVals: [], yVals: [], xErrVals: [], yErrVals: [] };
    g.xVals.push(r.x);
    g.yVals.push(r.y);
    if (r.x_err !== null && Number.isFinite(r.x_err)) g.xErrVals.push(r.x_err);
    if (r.y_err !== null && Number.isFinite(r.y_err)) g.yErrVals.push(r.y_err);
    groups.set(key, g);
  }

  const bySeries = new Map<string, { x: number; y: number; xerr: number; yerr: number; n: number }[]>();
  for (const [key, g] of groups.entries()) {
    const cKey = useColorGrouping ? key.split("||")[0]! : "__all__";
    const xMean = meanStd(g.xVals).mean;
    const yStats = meanStd(g.yVals);
    const xErrMean = g.xErrVals.length ? meanStd(g.xErrVals).mean : 0;
    const yErrMean = g.yErrVals.length ? meanStd(g.yErrVals).mean : NaN;
    const yErr = Number.isFinite(yErrMean) ? yErrMean : yStats.std;
    if (!Number.isFinite(xMean) || !Number.isFinite(yStats.mean) || !Number.isFinite(yErr)) continue;
    const s = bySeries.get(cKey) ?? [];
    s.push({ x: xMean, y: yStats.mean, xerr: Number.isFinite(xErrMean) ? xErrMean : 0, yerr: yErr, n: g.yVals.length });
    bySeries.set(cKey, s);
  }

  const mode = cfg.style === "errorbars_line" ? "lines+markers" : "markers";
  const traces: Record<string, unknown>[] = [];
  for (const [cKey, raw] of Array.from(bySeries.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
    const s = sortByX(raw);
    const parts = [namePrefix, useColorGrouping ? `${cfg.color}=${cKey}` : undefined].filter(Boolean);
    const tr: Record<string, unknown> = {
      type: "scatter",
      mode,
      name: parts.length ? parts.join(" · ") : undefined,
      x: s.map((p) => p.x),
      y: s.map((p) => p.y),
      text: s.map((p) => `n=${p.n}`),
      marker: { size: 8 },
      error_y: { type: "data", array: s.map((p) => p.yerr), visible: true },
    };
    if (cfg.xErr) tr.error_x = { type: "data", array: s.map((p) => p.xerr), visible: true };
    traces.push(tr);
  }
  return traces;
}

/**
 * Build a Plotly figure for one "Parameter vs parameter" plot from observation rows.
 * Multiple Y columns become one trace (or trace group) each.
 */
export function buildParamPlot(cfg: ParamPlotConfig, rows: Record<string, unknown>[]): ParamPlotResult {
  const ys = selectedYs(cfg);
  const multi = ys.length > 1;
  const yErrCol = multi ? "" : cfg.yErr;

  const csvHeader = ["spectrum_id", cfg.x, ...ys];
  if (cfg.color) csvHeader.push(cfg.color);
  if (cfg.xErr) csvHeader.push(cfg.xErr);
  if (yErrCol) csvHeader.push(yErrCol);
  const csvRows: (string | number | null)[][] = [];

  const pointsByY = new Map<string, Point[]>(ys.map((y) => [y, []]));
  for (const r of rows) {
    const x = cellToNumber(r[cfg.x]);
    if (x === null) continue;
    const sid = String(r.spectrum_id ?? "");
    const color = cfg.color ? cellToNumber(r[cfg.color]) : null;
    const xErr = cfg.xErr ? cellToNumber(r[cfg.xErr]) : null;
    const yErr = yErrCol ? cellToNumber(r[yErrCol]) : null;
    const yVals = ys.map((c) => cellToNumber(r[c]));
    if (yVals.every((v) => v === null)) continue;
    ys.forEach((c, i) => {
      const y = yVals[i];
      if (y !== null && y !== undefined) pointsByY.get(c)!.push({ spectrum_id: sid, x, y, color, x_err: xErr, y_err: yErr });
    });
    const row: (string | number | null)[] = [sid, x, ...yVals];
    if (cfg.color) row.push(color);
    if (cfg.xErr) row.push(xErr);
    if (yErrCol) row.push(yErr);
    csvRows.push(row);
  }

  const allPoints = Array.from(pointsByY.values()).flat();
  const colorBuckets = new Set<string>();
  if (cfg.color) {
    for (const p of allPoints) {
      colorBuckets.add(colorBucket(p.color));
      if (colorBuckets.size > 13) break;
    }
  }
  const hasColor = !!cfg.color && allPoints.some((p) => p.color !== null);
  // Only treat color as a grouping dimension when it behaves like a discrete factor.
  const discreteColor = hasColor && colorBuckets.size > 1 && colorBuckets.size <= 12;

  const yTitle = multi ? "value" : ys[0] ?? "";
  const titleY = multi ? ys.join(", ") : yTitle;
  const data: Record<string, unknown>[] = [];
  let layoutExtra: Record<string, unknown> = {};
  let titleSuffix = "";

  if (cfg.style === "scatter" || cfg.style === "line") {
    const isLine = cfg.style === "line";
    ys.forEach((yCol, i) => {
      const pts = isLine ? sortByX(pointsByY.get(yCol)!) : pointsByY.get(yCol)!;
      // Discrete color on a line plot: one line per color value (a continuous colorscale cannot color a line).
      if (isLine && discreteColor) {
        const byBucket = new Map<string, Point[]>();
        for (const p of pts) byBucket.set(colorBucket(p.color), [...(byBucket.get(colorBucket(p.color)) ?? []), p]);
        for (const [cKey, bp] of Array.from(byBucket.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
          data.push({
            type: "scatter",
            mode: "lines+markers",
            name: [multi ? yCol : undefined, `${cfg.color}=${cKey}`].filter(Boolean).join(" · "),
            x: bp.map((p) => p.x),
            y: bp.map((p) => p.y),
            text: bp.map((p) => p.spectrum_id),
            marker: { size: 6, symbol: SYMBOLS[i % SYMBOLS.length] },
          });
        }
        return;
      }
      const marker: Record<string, unknown> = { size: isLine ? 6 : 7 };
      if (multi) marker.symbol = SYMBOLS[i % SYMBOLS.length];
      if (hasColor) {
        marker.color = pts.map((p) => p.color);
        marker.colorscale = "Viridis";
        marker.showscale = i === 0;
        if (i === 0) marker.colorbar = { title: cfg.color };
      }
      data.push({
        type: "scatter",
        mode: isLine ? "lines+markers" : "markers",
        name: multi ? yCol : undefined,
        x: pts.map((p) => p.x),
        y: pts.map((p) => p.y),
        text: pts.map((p) => p.spectrum_id),
        marker,
      });
    });
    if (multi) layoutExtra = { showlegend: true, legend: { orientation: "h", y: -0.2 } };
  } else if (cfg.style === "boxplot") {
    const allX = Array.from(new Set(allPoints.map((p) => p.x))).sort((a, b) => a - b);
    for (const yCol of ys) {
      const pts = pointsByY.get(yCol)!;
      if (!multi && discreteColor) {
        const byBucket = new Map<string, Point[]>();
        for (const p of pts) byBucket.set(colorBucket(p.color), [...(byBucket.get(colorBucket(p.color)) ?? []), p]);
        for (const [cKey, bp] of Array.from(byBucket.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
          data.push({
            type: "box",
            name: `${cfg.color}=${cKey}`,
            x: bp.map((p) => stableNumberKey(p.x, 6)),
            y: bp.map((p) => p.y),
            boxpoints: false,
          });
        }
      } else {
        data.push({
          type: "box",
          name: multi ? yCol : undefined,
          x: pts.map((p) => stableNumberKey(p.x, 6)),
          y: pts.map((p) => p.y),
          boxpoints: false,
        });
      }
    }
    titleSuffix = " (boxplot grouped by X)";
    layoutExtra = {
      xaxis: { title: cfg.x, categoryorder: "array", categoryarray: allX.map((v) => stableNumberKey(v, 6)) },
      boxmode: "group",
      margin: { l: 60, r: 20, t: 40, b: 70 },
    };
  } else {
    for (const yCol of ys) {
      // With several Y columns, color grouping would multiply the series; group by X only.
      data.push(...aggregatedTraces(pointsByY.get(yCol)!, cfg, discreteColor && !multi, multi ? yCol : undefined));
    }
    titleSuffix = " (grouped by X)";
  }

  const empty = cfg.style === "boxplot" ? { type: "box", x: [], y: [] } : { type: "scatter", mode: "markers", x: [], y: [] };
  return {
    figure: {
      data: data.length ? data : [empty],
      layout: {
        title: `${titleY} vs ${cfg.x}${titleSuffix}`,
        xaxis: { title: cfg.x },
        yaxis: { title: yTitle },
        ...layoutExtra,
      },
    },
    csvHeader,
    csvRows,
  };
}

export function paramPlotCsv(res: ParamPlotResult): string {
  const esc = (v: string | number | null) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [res.csvHeader.map(esc).join(","), ...res.csvRows.map((r) => r.map(esc).join(","))].join("\n");
}
