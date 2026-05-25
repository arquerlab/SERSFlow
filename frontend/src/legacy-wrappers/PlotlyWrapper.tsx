import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { coerceDenseHeatmapAxes, publicationLayout, styleTraces } from "../lib/plotlyTheme";

export type PlotlyFigure = {
  data: any[];
  layout: Record<string, any>;
};

type PlotStyle = { mode: "overlay" | "stack"; stackSep: number };
type PlotlyWrapperProps = {
  figure: PlotlyFigure | null;
  previousFigure?: PlotlyFigure | null;
  plotStyle: PlotStyle;
  ghostOverlayEnabled: boolean;
  className?: string;
};

function applyStacking(data: any[], stackSep: number) {
  if (!Array.isArray(data) || data.length <= 1) return data;
  const sep = Number.isFinite(Number(stackSep)) ? Number(stackSep) : 0;
  if (sep === 0) return data;
  return data.map((tr, i) => {
    const y = Array.isArray(tr.y) ? tr.y : null;
    if (!y) return tr;
    return { ...tr, y: y.map((v: any) => (Number.isFinite(Number(v)) ? Number(v) + i * sep : v)) };
  });
}

function styleGhostTrace(tr: any) {
  const line = tr.line && typeof tr.line === "object" ? tr.line : {};
  return {
    ...tr,
    opacity: 0.25,
    line: { ...line, width: Math.max(1, Number((line as any).width || 2) - 1) },
    hoverinfo: "skip",
    showlegend: false,
  };
}

export const PlotlyWrapper = forwardRef<HTMLDivElement, PlotlyWrapperProps>(
  ({ figure, previousFigure, plotStyle, ghostOverlayEnabled, className }, ref) => {
  const divRef = useRef<HTMLDivElement | null>(null);
  useImperativeHandle(ref, () => divRef.current as HTMLDivElement);

  const combined = useMemo(() => {
    if (!figure) return null;
    const prevData =
      ghostOverlayEnabled && previousFigure?.data ? previousFigure.data.map(styleGhostTrace) : [];
    const curData = Array.isArray(figure.data) ? figure.data : [];
    const all = [...prevData, ...curData];
    if (plotStyle.mode === "stack") return { ...figure, data: applyStacking(all, plotStyle.stackSep) };
    return { ...figure, data: all };
  }, [figure, previousFigure, plotStyle.mode, plotStyle.stackSep, ghostOverlayEnabled]);

  const themed = useMemo(() => {
    if (!combined) return null;
    const data = styleTraces(combined.data, { kindHint: "unknown" });
    // Keep the current spectra legend convention if the author set a bottom-horizontal legend.
    const legend = (combined.layout as any)?.legend;
    const wantBottomLegend = legend && legend.orientation === "h" && typeof legend.y === "number" && legend.y < 0;
    let layout = publicationLayout(combined.layout, {
      showTitle: false,
      showLegend: (combined.layout as any)?.showlegend ?? true,
      legendBottomHorizontal: !!wantBottomLegend,
    });
    layout = coerceDenseHeatmapAxes(layout, { maxTickLabels: 40 });
    return { data, layout };
  }, [combined]);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;
    if (!themed) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, themed.data, themed.layout, {
      responsive: true,
      // Let the page/body receive wheel scroll unless the user deliberately zooms (e.g. pinch).
      // Prevents the plot from “eating” scroll, which makes the sidebar feel fixed.
      scrollZoom: false,
    });
  }, [themed]);

  return <div ref={divRef} className={className} />;
}
);

