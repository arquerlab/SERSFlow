/** S1 "Test peak model" figures (pure, Plotly JSON). */

export type ScanPoint = {
  value: number;
  error: string | null;
  chi2?: number | null;
  redchi?: number | null;
  area_pct?: Record<string, number | null>;
};

const COLORS = ["#e67e22", "#3498db", "#9b59b6", "#1abc9c", "#e74c3c", "#f39c12", "#2ecc71"];

/** Evenly spaced grid from..to with n points (n >= 2). */
export function scanGrid(from: number, to: number, n: number): number[] {
  const k = Math.max(2, Math.min(101, Math.floor(n)));
  return Array.from({ length: k }, (_, i) => from + ((to - from) * i) / (k - 1));
}

export function chi2Figure(points: ScanPoint[], label: string, bestValue: number | null) {
  const ok = points.filter((p) => !p.error && p.chi2 != null);
  return {
    data: [
      { type: "scatter", mode: "lines+markers", x: ok.map((p) => p.value), y: ok.map((p) => p.chi2), name: "χ²", line: { color: "#2c3e50" } },
      ...(bestValue != null
        ? [{ type: "scatter", mode: "markers", x: [bestValue], y: [Math.min(...ok.map((p) => p.chi2 as number))], name: "minimum", marker: { color: "#e74c3c", size: 10 } }]
        : []),
    ],
    layout: {
      height: 240,
      margin: { l: 60, r: 10, t: 24, b: 40 },
      title: { text: `χ² vs ${label}`, font: { size: 12 } },
      xaxis: { title: { text: label } },
      yaxis: { title: { text: "χ²" } },
      showlegend: false,
    },
  };
}

export function areaPctFigure(points: ScanPoint[], label: string) {
  const ok = points.filter((p) => !p.error && p.area_pct);
  const ids = [...new Set(ok.flatMap((p) => Object.keys(p.area_pct ?? {})))];
  return {
    data: ids.map((id, i) => ({
      type: "scatter",
      mode: "lines+markers",
      x: ok.map((p) => p.value),
      y: ok.map((p) => p.area_pct?.[id] ?? null),
      name: id,
      line: { color: COLORS[i % COLORS.length] },
    })),
    layout: {
      height: 240,
      margin: { l: 60, r: 10, t: 24, b: 40 },
      title: { text: `%area vs ${label}`, font: { size: 12 } },
      xaxis: { title: { text: label } },
      yaxis: { title: { text: "%area" } },
      legend: { orientation: "h", y: -0.3 },
    },
  };
}

export type NoiseResult = {
  x: number[];
  y: number[];
  best_y_hat: number[];
  overlay: Array<Record<string, number[]>>;
  components: Array<{ component_id: string; area_pct: Array<number | null>; area_pct_best: number | null }>;
};

/** Replicate component curves over the data: unstable components spread visibly (CasaXPS Test Peak Model). */
export function overlayFigure(r: NoiseResult, invertX: boolean) {
  const ids = [...new Set(r.overlay.flatMap((o) => Object.keys(o)))];
  const traces: Record<string, unknown>[] = [
    { type: "scatter", mode: "markers", x: r.x, y: r.y, name: "data", marker: { size: 3, color: "#2c3e50" } },
    { type: "scatter", mode: "lines", x: r.x, y: r.best_y_hat, name: "best fit", line: { color: "#e74c3c", width: 1.5 } },
  ];
  ids.forEach((id, i) => {
    r.overlay.forEach((o, k) => {
      if (!o[id]) return;
      traces.push({
        type: "scatter",
        mode: "lines",
        x: r.x,
        y: o[id],
        name: id,
        legendgroup: id,
        showlegend: k === 0,
        line: { color: COLORS[i % COLORS.length], width: 0.7 },
        opacity: 0.45,
      });
    });
  });
  return {
    data: traces,
    layout: {
      height: 280,
      margin: { l: 60, r: 10, t: 24, b: 40 },
      title: { text: "Replicate fits (components)", font: { size: 12 } },
      xaxis: { title: { text: "x" }, autorange: invertX ? "reversed" : true },
      legend: { orientation: "h", y: -0.25 },
    },
  };
}

export function areaHistogramFigure(r: NoiseResult) {
  return {
    data: r.components.map((c, i) => ({
      type: "histogram",
      x: c.area_pct.filter((v): v is number => typeof v === "number"),
      name: c.component_id,
      opacity: 0.6,
      marker: { color: COLORS[i % COLORS.length] },
    })),
    layout: {
      height: 240,
      barmode: "overlay",
      margin: { l: 50, r: 10, t: 24, b: 40 },
      title: { text: "%area across replicates", font: { size: 12 } },
      xaxis: { title: { text: "%area" } },
      legend: { orientation: "h", y: -0.3 },
    },
  };
}
