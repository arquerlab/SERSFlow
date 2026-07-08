import type { CsvRow } from "./export";
import type { PcaLikeResult } from "./types";
import type { PlotlyFigure } from "../legacy-wrappers/PlotlyWrapper";

const RAMAN_SHIFT_AXIS_TITLE = "Raman Shift (cm⁻¹)";

function pcIndex1To0(pc: number): number {
  const n = Math.floor(pc);
  return Math.max(0, n - 1);
}

function getScores(result: PcaLikeResult): number[][] | null {
  const s = result.scores;
  if (!Array.isArray(s) || !s.length || !Array.isArray(s[0])) return null;
  return s as number[][];
}

function getSpectrumIds(result: PcaLikeResult): string[] | null {
  const ids = result.spectrum_ids;
  if (!Array.isArray(ids) || !ids.length) return null;
  return ids.map(String);
}

function getFeatureNames(result: PcaLikeResult): string[] | null {
  if (Array.isArray(result.feature_names) && result.feature_names.length) return result.feature_names.map(String);
  // FPCA discrete uses synthetic w0.. but backend currently uses w{i} internally and returns feature_names there.
  // For FPCA fda, `components` correspond to grid points; prefer x_cm1 for display if present.
  if (Array.isArray(result.x_cm1) && result.x_cm1.length) return result.x_cm1.map((x) => `cm1_${Number(x).toFixed(2)}`);
  return null;
}

function scalerTitleSuffix(result: PcaLikeResult): string {
  const scaler = result.scaler ?? result.pca_preprocessing?.scaler;
  return scaler === "standard" ? " (StandardScaler)" : "";
}

export function buildScoresScatter(
  result: PcaLikeResult,
  opts: {
    xPc: number;
    yPc: number;
    xOverride?: { values: (number | null)[]; label: string };
    yOverride?: { values: (number | null)[]; label: string };
    colorBy?: { values: (number | null)[]; label: string };
  }
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const scores = getScores(result);
  if (!scores) return null;
  const ids = getSpectrumIds(result) ?? scores.map((_, i) => String(i));
  const xi = pcIndex1To0(opts.xPc);
  const yi = pcIndex1To0(opts.yPc);
  const pcX = scores.map((r) => (typeof r[xi] === "number" ? r[xi] : null));
  const pcY = scores.map((r) => (typeof r[yi] === "number" ? r[yi] : null));
  if (scores[0].length <= Math.max(xi, yi)) return null;

  const x = opts.xOverride?.values?.length === ids.length ? opts.xOverride.values : pcX;
  const y = opts.yOverride?.values?.length === ids.length ? opts.yOverride.values : pcY;
  const xLabel = opts.xOverride?.values?.length === ids.length ? opts.xOverride.label : `PC${xi + 1}`;
  const yLabel = opts.yOverride?.values?.length === ids.length ? opts.yOverride.label : `PC${yi + 1}`;

  const title = `Scores scatter (${xLabel} vs ${yLabel})${scalerTitleSuffix(result)}`;
  const figure: PlotlyFigure = {
    data: [
      {
        type: "scatter",
        mode: "markers",
        x,
        y,
        text: ids,
        marker: { size: 6 },
        hovertemplate: "%{text}<br>x=%{x}<br>y=%{y}<extra></extra>",
      },
    ],
    layout: {
      title,
      xaxis: { title: { text: xLabel } },
      yaxis: { title: { text: yLabel } },
    },
  };

  if (opts.colorBy?.values?.length === ids.length) {
    const c = opts.colorBy.values;
    const any = c.some((v) => typeof v === "number" && Number.isFinite(v));
    if (any) {
      (figure.data[0] as any).marker = {
        ...(figure.data[0] as any).marker,
        color: c,
        colorscale: "Viridis",
        showscale: true,
        colorbar: { title: opts.colorBy.label },
      };
    }
  }

  const csvRows: CsvRow[] = ids.map((sid, i) => {
    const row: CsvRow = { spectrum_id: sid, [xLabel]: x[i], [yLabel]: y[i] };
    if (opts.colorBy?.values?.length === ids.length) row[opts.colorBy.label] = opts.colorBy.values[i] ?? null;
    return row;
  });
  const defaultName = `scores_scatter_${safeKey(xLabel)}_vs_${safeKey(yLabel)}`;
  return { figure, csvRows, title, defaultName };
}

function safeKey(label: string): string {
  const s = String(label || "").trim();
  return (s || "axis").replace(/[^a-zA-Z0-9._-]+/g, "_");
}

export function buildScree(
  result: PcaLikeResult
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const evr = Array.isArray(result.explained_variance_ratio) ? result.explained_variance_ratio : null;
  if (!evr || !evr.length) return null;
  const xs = evr.map((_, i) => i + 1);
  const title = `Scree (explained variance ratio)${scalerTitleSuffix(result)}`;
  const figure: PlotlyFigure = {
    data: [{ type: "bar", x: xs, y: evr }],
    layout: { title, xaxis: { title: { text: "Component" } }, yaxis: { title: { text: "Explained variance ratio" } } },
  };
  const csvRows: CsvRow[] = evr.map((v, i) => ({ component: i + 1, explained_variance_ratio: v }));
  return { figure, csvRows, title, defaultName: "scree" };
}

export function buildCumulativeEvr(
  result: PcaLikeResult
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const evr = Array.isArray(result.explained_variance_ratio) ? result.explained_variance_ratio : null;
  if (!evr || !evr.length) return null;
  let acc = 0;
  const cum = evr.map((v) => (acc += Number(v) || 0));
  const xs = evr.map((_, i) => i + 1);
  const title = `Cumulative explained variance${scalerTitleSuffix(result)}`;
  const figure: PlotlyFigure = {
    data: [{ type: "scatter", mode: "lines+markers", x: xs, y: cum }],
    layout: { title, xaxis: { title: { text: "Component" } }, yaxis: { title: { text: "Cumulative explained variance" }, range: [0, 1] } },
  };
  const csvRows: CsvRow[] = evr.map((v, i) => ({ component: i + 1, explained_variance_ratio: v, cumulative_explained_variance: cum[i] }));
  return { figure, csvRows, title, defaultName: "cumulative_evr" };
}

export function buildScoresPairplot(
  result: PcaLikeResult,
  opts: {
    pcs: number[];
    maxPcs?: number;
    colorBy?: { values: (number | null)[]; label: string };
  }
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const scores = getScores(result);
  if (!scores) return null;
  const ids = getSpectrumIds(result) ?? scores.map((_, i) => String(i));
  const maxPcs = opts.maxPcs ?? 8;
  const pcs = (opts.pcs ?? []).map((p) => Math.max(1, Math.floor(p))).filter((p) => Number.isFinite(p));
  const uniq = Array.from(new Set(pcs)).slice(0, maxPcs);
  if (uniq.length < 2) return null;
  const dims = uniq
    .map((pc1) => {
      const i0 = pcIndex1To0(pc1);
      if (scores[0].length <= i0) return null;
      return { label: `PC${pc1}`, values: scores.map((r) => r[i0] ?? null) };
    })
    .filter(Boolean) as any[];
  if (dims.length < 2) return null;
  const title = `Scores pairplot (PC${uniq[0]}…PC${uniq[uniq.length - 1]})${scalerTitleSuffix(result)}`;
  const figure: PlotlyFigure = {
    data: [
      {
        type: "splom",
        dimensions: dims,
        text: ids,
        marker: { size: 5, opacity: 0.65 },
      },
    ],
    // SPLoM needs a bit more breathing room for axis labels.
    layout: { title, height: 650, margin: { l: 70, r: 20, t: 20, b: 70 } },
  };

  if (opts.colorBy?.values?.length === ids.length) {
    const c = opts.colorBy.values;
    const any = c.some((v) => typeof v === "number" && Number.isFinite(v));
    if (any) {
      (figure.data[0] as any).marker = {
        ...(figure.data[0] as any).marker,
        color: c,
        colorscale: "Viridis",
        showscale: true,
        colorbar: { title: opts.colorBy.label },
      };
    }
  }
  const csvRows: CsvRow[] = ids.map((sid, rowIdx) => {
    const row: CsvRow = { spectrum_id: sid };
    for (const pc1 of uniq) {
      const i0 = pcIndex1To0(pc1);
      row[`PC${pc1}`] = scores[rowIdx]?.[i0] ?? null;
    }
    return row;
  });
  const defaultName = `scores_pairplot_PC${uniq[0]}_to_PC${uniq[uniq.length - 1]}`;
  return { figure, csvRows, title, defaultName };
}

export function buildScoresPcVsMetaSubplots(
  result: PcaLikeResult,
  opts: {
    pcs: number[];
    xMeta: { values: (number | null)[]; label: string };
    maxPcs?: number;
  }
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const scores = getScores(result);
  if (!scores) return null;
  const ids = getSpectrumIds(result) ?? scores.map((_, i) => String(i));
  if (opts.xMeta.values.length !== ids.length) return null;
  const pcs = (opts.pcs ?? [])
    .map((p) => Math.max(1, Math.floor(p)))
    .filter((p) => Number.isFinite(p));
  const uniq = Array.from(new Set(pcs)).slice(0, Math.max(1, opts.maxPcs ?? 12));
  if (!uniq.length) return null;

  const validPcs = uniq.filter((pc1) => scores[0].length > pcIndex1To0(pc1));
  if (!validPcs.length) return null;

  const cols = validPcs.length >= 3 ? 2 : 1;
  const rows = Math.ceil(validPcs.length / cols);
  const gapX = 0.08;
  const gapY = 0.12;
  const cellW = (1 - gapX * (cols - 1)) / cols;
  const cellH = (1 - gapY * (rows - 1)) / rows;

  const data: any[] = [];
  const layout: Record<string, any> = {
    title: `PC vs ${opts.xMeta.label}${scalerTitleSuffix(result)}`,
    height: Math.max(420, rows * 320),
    margin: { l: 60, r: 20, t: 30, b: 60 },
    annotations: [],
    showlegend: false,
  };

  validPcs.forEach((pc1, idx) => {
    const pc0 = pcIndex1To0(pc1);
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const x0 = col * (cellW + gapX);
    const x1 = x0 + cellW;
    const y1 = 1 - row * (cellH + gapY);
    const y0 = y1 - cellH;
    const axisSuffix = idx === 0 ? "" : String(idx + 1);
    const xaxisKey = `xaxis${axisSuffix}`;
    const yaxisKey = `yaxis${axisSuffix}`;

    layout[xaxisKey] = {
      domain: [x0, x1],
      anchor: `y${axisSuffix || ""}`,
      title: { text: opts.xMeta.label },
    };
    layout[yaxisKey] = {
      domain: [y0, y1],
      anchor: `x${axisSuffix || ""}`,
      title: { text: `PC${pc1}` },
    };
    layout.annotations.push({
      text: `PC${pc1}`,
      x: (x0 + x1) / 2,
      y: y1 + 0.04,
      xref: "paper",
      yref: "paper",
      showarrow: false,
      font: { size: 13, color: "black" },
    });

    data.push({
      type: "scatter",
      mode: "markers",
      x: opts.xMeta.values,
      y: scores.map((r) => (typeof r[pc0] === "number" ? r[pc0] : null)),
      text: ids,
      marker: { size: 6 },
      hovertemplate: "%{text}<br>x=%{x}<br>y=%{y}<extra></extra>",
      xaxis: `x${axisSuffix}`,
      yaxis: `y${axisSuffix}`,
      showlegend: false,
    });
  });

  const csvRows: CsvRow[] = ids.map((sid, i) => {
    const row: CsvRow = { spectrum_id: sid, [opts.xMeta.label]: opts.xMeta.values[i] ?? null };
    for (const pc1 of validPcs) {
      row[`PC${pc1}`] = scores[i]?.[pcIndex1To0(pc1)] ?? null;
    }
    return row;
  });

  return {
    figure: { data, layout },
    csvRows,
    title: `PC vs ${opts.xMeta.label}`,
    defaultName: `pc_vs_${safeKey(opts.xMeta.label)}_${validPcs.map((pc) => `PC${pc}`).join("_")}`,
  };
}

export function buildLoadingsTopN(
  result: PcaLikeResult,
  opts: { pc: number; topN: number }
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const comps = Array.isArray(result.components) ? (result.components as number[][]) : null;
  if (!comps || !comps.length || !Array.isArray(comps[0])) return null;
  const names = getFeatureNames(result);
  const pc1 = Math.max(1, Math.floor(opts.pc));
  const pc0 = pcIndex1To0(pc1);
  if (pc0 >= comps.length) return null;
  const vec = comps[pc0];
  const nFeat = vec.length;
  const featNames = names && names.length === nFeat ? names : Array.from({ length: nFeat }, (_, i) => `f${i}`);
  const topN = Math.max(1, Math.min(200, Math.floor(opts.topN)));
  const idx = Array.from({ length: nFeat }, (_, i) => i)
    .sort((a, b) => Math.abs(Number(vec[b]) || 0) - Math.abs(Number(vec[a]) || 0))
    .slice(0, topN);
  const xs = idx.map((i) => featNames[i]);
  const ys = idx.map((i) => Number(vec[i]) || 0);
  const title = `Loadings (PC${pc1}) — top ${topN} by |loading|${scalerTitleSuffix(result)}`;
  const figure: PlotlyFigure = {
    data: [{ type: "bar", x: xs, y: ys }],
    layout: { title, xaxis: { tickangle: -45 }, margin: { l: 70, r: 20, t: 20, b: 140 } },
  };
  const csvRows: CsvRow[] = idx.map((i) => ({ component: pc1, feature_name: featNames[i], loading: Number(vec[i]) || 0 }));
  const defaultName = `loadings_top${topN}_PC${pc1}`;
  return { figure, csvRows, title, defaultName };
}

function getXcm1(result: PcaLikeResult, nFeat: number): number[] | null {
  if (Array.isArray(result.x_cm1) && result.x_cm1.length === nFeat) {
    return result.x_cm1.map((v) => Number(v)).filter((v) => Number.isFinite(v));
  }
  const names = Array.isArray(result.feature_names) && result.feature_names.length === nFeat ? result.feature_names : null;
  if (!names) return null;
  const xs = names.map((s) => {
    const m = String(s).match(/-?\d+(\.\d+)?/);
    return m ? Number(m[0]) : NaN;
  });
  if (!xs.length || xs.some((v) => !Number.isFinite(v))) return null;
  return xs;
}

export function buildLoadingsSpectrum(
  result: PcaLikeResult,
  opts: { pcs: number[]; maxPcs?: number }
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const comps = Array.isArray(result.components) ? (result.components as number[][]) : null;
  if (!comps || !comps.length || !Array.isArray(comps[0])) return null;
  const nFeat = comps[0].length;
  const x = getXcm1(result, nFeat);
  if (!x) return null;

  const maxPcs = opts.maxPcs ?? 6;
  const pcs = (opts.pcs ?? []).map((p) => Math.max(1, Math.floor(p))).filter((p) => Number.isFinite(p));
  const uniq = Array.from(new Set(pcs)).filter((pc1) => pcIndex1To0(pc1) < comps.length).slice(0, maxPcs);
  if (!uniq.length) return null;

  const traces = uniq.map((pc1) => {
    const pc0 = pcIndex1To0(pc1);
    const y = (comps[pc0] ?? []).map((v) => (Number.isFinite(Number(v)) ? Number(v) : null));
    return {
      type: "scatter",
      mode: "lines",
      name: `PC${pc1}`,
      x,
      y,
      hovertemplate: `PC${pc1}<br>x=%{x}<br>loading=%{y}<extra></extra>`,
    };
  });

  const title = `Loadings spectra (${uniq.map((pc1) => `PC${pc1}`).join(", ")})${scalerTitleSuffix(result)}`;
  const figure: PlotlyFigure = {
    data: traces as any[],
    layout: {
      title,
      xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE } },
      yaxis: { title: { text: "Loading" } },
      // Bottom horizontal legend reads well for multiple component curves.
      legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
      margin: { l: 60, r: 20, t: 20, b: 95 },
    },
  };

  const csvRows: CsvRow[] = x.map((xv, i) => {
    const row: CsvRow = { x_cm1: xv };
    for (const pc1 of uniq) {
      const pc0 = pcIndex1To0(pc1);
      row[`PC${pc1}`] = (comps[pc0] ?? [])[i] ?? null;
    }
    return row;
  });
  const defaultName = `loadings_spectra_${uniq.map((pc1) => `PC${pc1}`).join("_")}`;
  return { figure, csvRows, title, defaultName };
}

export function buildLoadingsHeatmap(
  result: PcaLikeResult,
  opts?: { pcs?: number[]; maxFeatures?: number; maxComponents?: number }
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const comps = Array.isArray(result.components) ? (result.components as number[][]) : null;
  if (!comps || !comps.length || !Array.isArray(comps[0])) return null;
  const maxComponents = opts?.maxComponents ?? 10;
  const maxFeatures = opts?.maxFeatures ?? 120;
  const rawPcs = (opts?.pcs ?? []).map((p) => Math.max(1, Math.floor(p))).filter((p) => Number.isFinite(p));
  const uniqPcs = Array.from(new Set(rawPcs)).filter((pc) => pcIndex1To0(pc) < comps.length);
  const pcs = (uniqPcs.length ? uniqPcs : Array.from({ length: Math.min(comps.length, maxComponents) }, (_, i) => i + 1)).slice(
    0,
    maxComponents
  );
  const k = pcs.length;
  const p = comps[0].length;
  const names = getFeatureNames(result);
  const featNames = names && names.length === p ? names : Array.from({ length: p }, (_, i) => `f${i}`);

  // If there are too many features, keep the features with highest max |loading| across first k components.
  let featIdx = Array.from({ length: p }, (_, i) => i);
  if (p > maxFeatures) {
    const scores = featIdx
      .map((i) => ({
        i,
        m: Math.max(...pcs.map((pc1) => Math.abs(Number(comps[pcIndex1To0(pc1)]?.[i]) || 0))),
      }))
      .sort((a, b) => b.m - a.m)
      .slice(0, maxFeatures);
    featIdx = scores.map((x) => x.i);
  }
  const x = featIdx.map((i) => featNames[i]);
  const y = pcs.map((pc1) => `PC${pc1}`);
  const z = pcs.map((pc1) => featIdx.map((i) => Number(comps[pcIndex1To0(pc1)]?.[i]) || 0));
  const title = `Loadings heatmap (${pcs.map((pc1) => `PC${pc1}`).join(", ")})${scalerTitleSuffix(result)}`;
  const figure: PlotlyFigure = {
    data: [{ type: "heatmap", x, y, z, colorbar: { title: "loading" } }],
    layout: { title, margin: { l: 70, r: 20, t: 20, b: 140 }, xaxis: { tickangle: -45 } },
  };
  const csvRows: CsvRow[] = [];
  for (let pc = 0; pc < k; pc++) {
    for (let j = 0; j < featIdx.length; j++) {
      csvRows.push({ component: pcs[pc], feature_name: x[j], loading: z[pc][j] });
    }
  }
  const defaultName = `loadings_heatmap_${pcs.map((pc1) => `PC${pc1}`).join("_")}`;
  return { figure, csvRows, title, defaultName };
}

