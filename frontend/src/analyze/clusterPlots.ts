import type { CsvRow } from "./export";
import type { ClusterResult, PcaLikeResult } from "./types";
import type { PlotlyFigure } from "../legacy-wrappers/PlotlyWrapper";

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

export function buildClusterOnScoresScatter(
  scoresResult: PcaLikeResult,
  cluster: ClusterResult,
  opts: { xPc: number; yPc: number }
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const scores = getScores(scoresResult);
  if (!scores) return null;
  const ids = getSpectrumIds(scoresResult);
  if (!ids || ids.length !== scores.length) return null;
  const labels = cluster.labels ?? {};
  const xi = pcIndex1To0(opts.xPc);
  const yi = pcIndex1To0(opts.yPc);
  if (scores[0].length <= Math.max(xi, yi)) return null;

  const byCluster = new Map<number, number[]>();
  for (let i = 0; i < ids.length; i++) {
    const sid = ids[i];
    const c = labels[sid];
    if (typeof c !== "number" || !Number.isFinite(c)) continue;
    const arr = byCluster.get(c) ?? [];
    arr.push(i);
    byCluster.set(c, arr);
  }
  if (!byCluster.size) return null;

  const clustersSorted = Array.from(byCluster.keys()).sort((a, b) => a - b);
  const traces = clustersSorted.map((c) => {
    const idx = byCluster.get(c)!;
    return {
      type: "scatter",
      mode: "markers",
      name: `Cluster ${c}`,
      x: idx.map((i) => scores[i][xi] ?? null),
      y: idx.map((i) => scores[i][yi] ?? null),
      text: idx.map((i) => ids[i]),
      marker: { size: 6, opacity: 0.75 },
      hovertemplate: "%{text}<br>cluster=" + c + "<br>x=%{x}<br>y=%{y}<extra></extra>",
    };
  });

  const title = `Cluster on scores (PC${xi + 1} vs PC${yi + 1})`;
  const figure: PlotlyFigure = {
    data: traces as any[],
    layout: {
      title,
      xaxis: { title: { text: `PC${xi + 1}` } },
      yaxis: { title: { text: `PC${yi + 1}` } },
      // Let the wrapper/theme choose legend placement; keep only plot-specific layout.
      legend: { orientation: "h" },
    },
  };

  const csvRows: CsvRow[] = [];
  for (let i = 0; i < ids.length; i++) {
    const sid = ids[i];
    const c = labels[sid];
    if (typeof c !== "number" || !Number.isFinite(c)) continue;
    csvRows.push({
      spectrum_id: sid,
      cluster: c,
      [`PC${xi + 1}`]: scores[i]?.[xi] ?? null,
      [`PC${yi + 1}`]: scores[i]?.[yi] ?? null,
    });
  }
  const defaultName = `cluster_on_scores_PC${xi + 1}_PC${yi + 1}`;
  return { figure, csvRows, title, defaultName };
}

export function buildClusterSizesBar(
  cluster: ClusterResult
): { figure: PlotlyFigure; csvRows: CsvRow[]; title: string; defaultName: string } | null {
  const labels = cluster.labels ?? {};
  const counts = new Map<number, number>();
  for (const k of Object.keys(labels)) {
    const c = labels[k];
    if (typeof c !== "number" || !Number.isFinite(c)) continue;
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  if (!counts.size) return null;
  const cs = Array.from(counts.keys()).sort((a, b) => a - b);
  const ys = cs.map((c) => counts.get(c) ?? 0);
  const title = "Cluster sizes";
  const figure: PlotlyFigure = {
    data: [{ type: "bar", x: cs.map((c) => String(c)), y: ys }],
    layout: { title, xaxis: { title: { text: "Cluster" } }, yaxis: { title: { text: "Count" } } },
  };
  const csvRows: CsvRow[] = cs.map((c) => ({ cluster: c, count: counts.get(c) ?? 0 }));
  return { figure, csvRows, title, defaultName: "cluster_sizes" };
}

