export type PlotlyTrace = Record<string, unknown>;
export type PlotlyLayout = Record<string, unknown>;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function deepMergeLayout(base: PlotlyLayout, override: unknown): PlotlyLayout {
  if (!isPlainObject(override)) return base;
  const out: PlotlyLayout = { ...base };
  for (const [k, v] of Object.entries(override)) {
    const cur = out[k];
    if (isPlainObject(cur) && isPlainObject(v)) out[k] = deepMergeLayout(cur, v);
    else out[k] = v;
  }
  return out;
}

function withDefault<T>(v: T | undefined, fallback: T): T {
  return v === undefined ? fallback : v;
}

function clamp01(x: number): number {
  if (!Number.isFinite(x)) return 1;
  return Math.max(0, Math.min(1, x));
}

export const prismCorePalette = [
  "#000000", // black
  "#0B2E6D", // dark blue
  "#C0392B", // muted red
  "#1E8449", // muted green
  "#6C3483", // muted purple
] as const;

// Extended muted palette (still non-neon) for >5 categories.
export const prismExtendedPalette = [
  ...prismCorePalette,
  "#7D6608", // olive
  "#1F618D", // muted blue
  "#7B241C", // dark red
  "#117864", // teal
  "#515A5A", // dark gray
  "#935116", // brown/orange
  "#2E4053", // slate
] as const;

export type PublicationLayoutOptions = {
  title?: string | null;
  showTitle?: boolean;
  margin?: { l?: number; r?: number; t?: number; b?: number };
  showLegend?: boolean;
  legendBottomHorizontal?: boolean;
};

export function publicationLayout(overrides?: PlotlyLayout, opts?: PublicationLayoutOptions): PlotlyLayout {
  const showTitle = !!opts?.showTitle;
  const titleText =
    typeof opts?.title === "string"
      ? opts?.title
      : typeof (overrides as any)?.title === "string"
        ? ((overrides as any).title as string)
        : null;

  const axisBase: PlotlyLayout = {
    showline: true,
    linewidth: 2,
    linecolor: "black",
    ticks: "outside",
    tickwidth: 2,
    tickcolor: "black",
    showgrid: false,
    zeroline: false,
    mirror: false,
    automargin: true,
    title: { font: { size: 15, color: "black" } },
  };

  const legendBase: PlotlyLayout =
    opts?.showLegend === false
      ? { traceorder: "normal" }
      : opts?.legendBottomHorizontal
        ? {
            orientation: "h",
            yanchor: "top",
            y: -0.25,
            xanchor: "center",
            x: 0.5,
            bgcolor: "rgba(0,0,0,0)",
            borderwidth: 0,
            font: { size: 12, color: "black" },
          }
        : {
            x: 1,
            xanchor: "right",
            y: 1,
            yanchor: "top",
            bgcolor: "rgba(0,0,0,0)",
            borderwidth: 0,
            font: { size: 12, color: "black" },
          };

  const base: PlotlyLayout = {
    plot_bgcolor: "white",
    paper_bgcolor: "white",
    font: { family: "Arial, sans-serif", size: 14, color: "black" },
    // Use a template so axis styling applies to all generated axes (e.g. SPLoM xaxis2/xaxis3...).
    template: {
      layout: {
        plot_bgcolor: "white",
        paper_bgcolor: "white",
        font: { family: "Arial, sans-serif", size: 14, color: "black" },
        xaxis: axisBase,
        yaxis: axisBase,
        legend: legendBase,
      },
    },
    title: showTitle && titleText ? { text: titleText, font: { size: 14, color: "black" } } : undefined,
    margin: {
      l: withDefault(opts?.margin?.l, 60),
      r: withDefault(opts?.margin?.r, 20),
      t: withDefault(opts?.margin?.t, 20),
      b: withDefault(opts?.margin?.b, 50),
    },
    xaxis: axisBase,
    yaxis: axisBase,
    legend: legendBase,
    showlegend: withDefault(opts?.showLegend, true),
  };

  // If the figure had a string title but titles are default-off, ensure we don't accidentally
  // display it via Plotly defaults; we keep it present only when explicitly enabled.
  const merged = deepMergeLayout(base, overrides ?? {});
  if (!showTitle) {
    // Support both legacy string `layout.title = "..."` and object `layout.title = {text:"..."}`
    if (typeof (merged as any).title === "string") (merged as any).title = undefined;
    if (isPlainObject((merged as any).title)) (merged as any).title = { ...(merged as any).title, text: undefined };
  }
  return merged;
}

export type StyleTracesOptions = {
  kindHint?: "spectra" | "scatter" | "bar" | "box" | "heatmap" | "splom" | "unknown";
  palette?: readonly string[];
  forceSpectraLines?: boolean;
  manyTraceOpacity?: number; // applied when > manyTraceThreshold
  manyTraceThreshold?: number;
};

function getLine(tr: PlotlyTrace): Record<string, unknown> {
  return isPlainObject(tr.line) ? (tr.line as Record<string, unknown>) : {};
}

function setLine(tr: PlotlyTrace, line: Record<string, unknown>): PlotlyTrace {
  return { ...tr, line };
}

function asNumber(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function shouldPreserveExplicitColor(tr: PlotlyTrace): boolean {
  const line = getLine(tr);
  if (typeof line.color === "string" && line.color) return true;
  const marker = isPlainObject(tr.marker) ? (tr.marker as Record<string, unknown>) : null;
  if (marker && (typeof marker.color === "string" || Array.isArray(marker.color))) return true;
  return false;
}

export function styleTraces(traces: unknown, opts?: StyleTracesOptions): PlotlyTrace[] {
  const arr = Array.isArray(traces) ? (traces as PlotlyTrace[]) : [];
  const palette = (opts?.palette?.length ? opts.palette : prismExtendedPalette) as readonly string[];
  const manyTraceThreshold = Math.max(1, Math.floor(opts?.manyTraceThreshold ?? 10));
  const manyTraceOpacity = clamp01(asNumber(opts?.manyTraceOpacity) ?? 0.8);
  const dense = arr.length > manyTraceThreshold;

  // For spectra we want a stable, readable palette and lines-only by default.
  const forceSpectraLines = opts?.forceSpectraLines ?? (opts?.kindHint === "spectra");

  let colorIdx = 0;
  return arr.map((tr) => {
    const type = typeof tr.type === "string" ? tr.type : "";
    const mode = typeof tr.mode === "string" ? tr.mode : "";

    let out: PlotlyTrace = { ...tr };

    // Spectra: keep clean lines, medium thickness, muted palette.
    if (forceSpectraLines && type === "scatter") {
      // If this trace is clearly an errorbar/points plot, don't force.
      const hasErrorBars = isPlainObject((out as any).error_y) || isPlainObject((out as any).error_x);
      const isMarkersOnly = mode.includes("markers") && !mode.includes("lines");
      if (!hasErrorBars && !isMarkersOnly) {
        out.mode = "lines";
      }

      const existingLine = getLine(out);
      const width = asNumber(existingLine.width) ?? 2;
      const nextColor = palette[colorIdx % palette.length] ?? "#000000";
      const lineColor = shouldPreserveExplicitColor(out)
        ? (existingLine.color as string | undefined)
        : (existingLine.color as string | undefined) ?? nextColor;
      if (!shouldPreserveExplicitColor(out)) colorIdx += 1;

      out = setLine(out, { ...existingLine, width: Math.max(1, width), color: lineColor });

      if (dense && out.opacity === undefined) out.opacity = manyTraceOpacity;
      // Ensure no markers sneak in unless explicitly requested.
      if ((out as any).marker !== undefined && out.mode === "lines") {
        // leave marker config in place, but it won't render without markers in mode
      }
      return out;
    }

    // Scatter markers: add thin black outline by default (Prism-like),
    // but do not override explicit marker styling or colorscales.
    if (type === "scatter" && mode.includes("markers")) {
      const marker = isPlainObject(out.marker) ? ({ ...(out.marker as any) } as Record<string, unknown>) : {};
      const line = isPlainObject(marker.line) ? ({ ...(marker.line as any) } as Record<string, unknown>) : {};
      if (line.color === undefined) line.color = "black";
      if (line.width === undefined) line.width = 1;
      marker.line = line;
      out.marker = marker;
      return out;
    }

    // Lines (non-spectra): ensure medium thickness and avoid markers by default.
    if (type === "scatter" && mode.includes("lines")) {
      const existingLine = getLine(out);
      const width = asNumber(existingLine.width) ?? 2;
      out = setLine(out, { ...existingLine, width: Math.max(1, width) });
      if (dense && out.opacity === undefined) out.opacity = manyTraceOpacity;
      return out;
    }

    return out;
  });
}

export type HeatmapLabelDensityOptions = { maxTickLabels?: number };

export function coerceDenseHeatmapAxes(layout: PlotlyLayout, opts?: HeatmapLabelDensityOptions): PlotlyLayout {
  const maxTickLabels = Math.max(10, Math.floor(opts?.maxTickLabels ?? 40));
  const x = isPlainObject(layout.xaxis) ? (layout.xaxis as PlotlyLayout) : {};
  const y = isPlainObject(layout.yaxis) ? (layout.yaxis as PlotlyLayout) : {};
  const xTickText = (x as any).ticktext;
  const yTickText = (y as any).ticktext;
  const xLen = Array.isArray(xTickText) ? xTickText.length : null;
  const yLen = Array.isArray(yTickText) ? yTickText.length : null;

  // If tick labels are dense, hide them and rely on hover.
  const denseX = typeof xLen === "number" && xLen > maxTickLabels;
  const denseY = typeof yLen === "number" && yLen > maxTickLabels;

  if (!denseX && !denseY) return layout;

  return {
    ...layout,
    xaxis: { ...x, showticklabels: denseX ? false : (x as any).showticklabels },
    yaxis: { ...y, showticklabels: denseY ? false : (y as any).showticklabels },
  };
}

