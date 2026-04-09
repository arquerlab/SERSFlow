import { useEffect, useMemo, useRef } from "react";
import Plotly from "plotly.js-dist-min";

type PlotlyFigure = {
  data: any[];
  layout: Record<string, any>;
};

type PlotStyle = { mode: "overlay" | "stack"; stackSep: number };

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

export function PlotlyWrapper({
  figure,
  previousFigure,
  plotStyle,
  ghostOverlayEnabled,
  className,
}: {
  figure: PlotlyFigure | null;
  previousFigure?: PlotlyFigure | null;
  plotStyle: PlotStyle;
  ghostOverlayEnabled: boolean;
  className?: string;
}) {
  const divRef = useRef<HTMLDivElement | null>(null);

  const combined = useMemo(() => {
    if (!figure) return null;
    const prevData =
      ghostOverlayEnabled && previousFigure?.data ? previousFigure.data.map(styleGhostTrace) : [];
    const curData = Array.isArray(figure.data) ? figure.data : [];
    const all = [...prevData, ...curData];
    if (plotStyle.mode === "stack") return { ...figure, data: applyStacking(all, plotStyle.stackSep) };
    return { ...figure, data: all };
  }, [figure, previousFigure, plotStyle.mode, plotStyle.stackSep, ghostOverlayEnabled]);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;
    if (!combined) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, combined.data, combined.layout, { responsive: true });
  }, [combined]);

  return <div ref={divRef} className={className} style={{ minHeight: 420 }} />;
}

