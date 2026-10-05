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
  onPlotClick?: (event: any) => void;
  onPlotHover?: (event: any) => void;
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

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
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

function constrainPlotDom(el: HTMLDivElement) {
  el.style.width = "100%";
  el.style.maxWidth = "100%";
  const svg = el.querySelector(".svg-container") as HTMLElement | null;
  if (svg) {
    svg.style.width = "100%";
    svg.style.maxWidth = "100%";
  }
  const plotRoot = el.querySelector(".js-plotly-plot") as HTMLElement | null;
  if (plotRoot) {
    plotRoot.style.width = "100%";
    plotRoot.style.maxWidth = "100%";
  }
}

export const PlotlyWrapper = forwardRef<HTMLDivElement, PlotlyWrapperProps>(
  ({ figure, previousFigure, plotStyle, ghostOverlayEnabled, className, onPlotClick, onPlotHover }, ref) => {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const divRef = useRef<HTMLDivElement | null>(null);
  /** Monotonic id so only the latest draw applies post-await DOM work. */
  const drawIdRef = useRef(0);
  /** Serialize Plotly calls — a cancelled newPlot/react must finish before the next starts. */
  const drawChainRef = useRef<Promise<void>>(Promise.resolve());
  const drawingRef = useRef(false);
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
    // Theme traces and also suppress Plotly's default "trace 0" legend labels.
    // Plotly will render a legend entry for unnamed traces when showlegend=true.
    const data = styleTraces(combined.data, { kindHint: "unknown" }).map((tr) => {
      const name = typeof (tr as any).name === "string" ? ((tr as any).name as string).trim() : "";
      if (!name && (tr as any).showlegend === undefined) return { ...tr, showlegend: false };
      return tr;
    });
    // Prefer author legend placement. Bottom-horizontal (y < 0) uses the spectra
    // convention; top-of-plot legends (e.g. older fit figures) must not be remapped
    // to the default right-side legend, which overlaps titles.
    const legend = (combined.layout as any)?.legend;
    const wantBottomLegend =
      legend && legend.orientation === "h" && typeof legend.y === "number" && legend.y < 0;
    const hasAuthorLegend = isPlainObject(legend);
    const hasTitle =
      (typeof (combined.layout as any)?.title === "string" && !!(combined.layout as any).title) ||
      (isPlainObject((combined.layout as any)?.title) &&
        typeof ((combined.layout as any).title as any).text === "string" &&
        !!((combined.layout as any).title as any).text);
    const hasSubplots =
      isPlainObject((combined.layout as any)?.yaxis2) || isPlainObject((combined.layout as any)?.yaxis3);
    let layout = publicationLayout(combined.layout, {
      // Fit/residual figures carry spectrum id + GoF in the title — keep it.
      showTitle: hasTitle && hasSubplots,
      showLegend: (combined.layout as any)?.showlegend ?? true,
      legendBottomHorizontal: !!wantBottomLegend,
      margin: hasSubplots
        ? {
            l: Number((combined.layout as any)?.margin?.l) || 60,
            r: Number((combined.layout as any)?.margin?.r) || 20,
            t: Number((combined.layout as any)?.margin?.t) || 48,
            b: Number((combined.layout as any)?.margin?.b) || 80,
          }
        : undefined,
    });
    if (hasAuthorLegend && !wantBottomLegend) {
      const src = legend as Record<string, unknown>;
      const cur = isPlainObject((layout as any).legend) ? ((layout as any).legend as Record<string, unknown>) : {};
      (layout as any).legend = { ...cur, ...src };
    }
    // publicationLayout only keeps string titles; restore object titles (HTML GoF line).
    if (hasSubplots && isPlainObject((combined.layout as any).title)) {
      const src = (combined.layout as any).title as Record<string, unknown>;
      const cur = isPlainObject((layout as any).title) ? ((layout as any).title as Record<string, unknown>) : {};
      (layout as any).title = { ...cur, ...src };
    }
    // Ensure secondary axes keep domain splits after theme merge.
    if (hasSubplots && isPlainObject((combined.layout as any).yaxis2)) {
      const src = (combined.layout as any).yaxis2 as Record<string, unknown>;
      const cur = isPlainObject((layout as any).yaxis2) ? ((layout as any).yaxis2 as Record<string, unknown>) : {};
      (layout as any).yaxis2 = {
        ...cur,
        ...src,
        domain: src.domain ?? cur.domain,
        title: src.title ?? cur.title,
        zeroline: src.zeroline ?? true,
        showgrid: false,
        showline: true,
        linewidth: 2,
        linecolor: "black",
        automargin: true,
      };
    }
    if (hasSubplots && isPlainObject((combined.layout as any).yaxis)) {
      const src = (combined.layout as any).yaxis as Record<string, unknown>;
      const cur = isPlainObject((layout as any).yaxis) ? ((layout as any).yaxis as Record<string, unknown>) : {};
      (layout as any).yaxis = { ...cur, ...src, domain: src.domain ?? cur.domain };
    }
    if (hasSubplots && isPlainObject((combined.layout as any).xaxis)) {
      const src = (combined.layout as any).xaxis as Record<string, unknown>;
      const cur = isPlainObject((layout as any).xaxis) ? ((layout as any).xaxis as Record<string, unknown>) : {};
      (layout as any).xaxis = { ...cur, ...src, domain: src.domain ?? cur.domain, anchor: src.anchor ?? cur.anchor };
    }
    if (hasSubplots && typeof (combined.layout as any).height === "number") {
      (layout as any).height = (combined.layout as any).height;
    }
    // Always fill the host; drop fixed widths so plots cannot blow past the Analyze right pane.
    (layout as any).autosize = true;
    if ((layout as any).width !== undefined) delete (layout as any).width;
    layout = coerceDenseHeatmapAxes(layout, { maxTickLabels: 40 });
    return { data, layout };
  }, [combined]);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;

    if (!themed) {
      const drawId = ++drawIdRef.current;
      drawChainRef.current = drawChainRef.current
        .catch(() => undefined)
        .then(async () => {
          if (drawId !== drawIdRef.current) return;
          drawingRef.current = true;
          try {
            Plotly.purge(el);
          } catch {
            // ignore
          } finally {
            drawingRef.current = false;
          }
        });
      return;
    }

    const opts = {
      responsive: true,
      scrollZoom: false,
    } as const;

    const drawId = ++drawIdRef.current;
    const payload = themed;
    // Always newPlot — Plotly.react blanks when trace count is unchanged (same-size subset switch).

    drawChainRef.current = drawChainRef.current
      .catch(() => undefined)
      .then(async () => {
        // Superseded before start: do not purge (that left a blank plot when cleanup raced).
        if (drawId !== drawIdRef.current) return;
        drawingRef.current = true;
        try {
          // Purge+newPlot must be atomic: never return between purge and newPlot or the DOM stays blank.
          Plotly.purge(el);
          await Plotly.newPlot(el, payload.data, payload.layout, opts);
        } catch {
          if (drawId !== drawIdRef.current) return;
          try {
            Plotly.purge(el);
            await Plotly.newPlot(el, payload.data, payload.layout, opts);
          } catch {
            return;
          }
        } finally {
          drawingRef.current = false;
        }
        if (drawId !== drawIdRef.current) return;
        constrainPlotDom(el);
        try {
          Plotly.Plots.resize(el);
        } catch {
          // ignore
        }
      });

    // No cancelled flag: supersession is drawId-only. Cancelling after purge was leaving a blank plot.
  }, [themed]);

  // Observe host size once — recreating the observer on every figure change races with Plotly.react.
  useEffect(() => {
    const el = divRef.current;
    const host = wrapRef.current ?? el;
    if (!el || !host) return;
    const ro = new ResizeObserver(() => {
      if (drawingRef.current) return;
      try {
        constrainPlotDom(el);
        Plotly.Plots.resize(el);
      } catch {
        // ignore
      }
    });
    ro.observe(host);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = divRef.current as any;
    if (!el || !onPlotClick) return;
    el.on("plotly_click", onPlotClick);
    return () => {
      el.removeListener?.("plotly_click", onPlotClick);
    };
  }, [onPlotClick]);

  useEffect(() => {
    const el = divRef.current as any;
    if (!el || !onPlotHover) return;
    el.on("plotly_hover", onPlotHover);
    return () => {
      el.removeListener?.("plotly_hover", onPlotHover);
    };
  }, [onPlotHover]);

  const wrapClass = [className ? `${className}-wrap` : null, "plot-host-wrap"].filter(Boolean).join(" ");
  return (
    <div ref={wrapRef} className={wrapClass} style={{ width: "100%", maxWidth: "100%", minWidth: 0, overflow: "hidden" }}>
      <div ref={divRef} className={className} style={{ width: "100%", maxWidth: "100%", minHeight: "inherit" }} />
    </div>
  );
}
);
