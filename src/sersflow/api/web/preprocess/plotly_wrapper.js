import React from "https://esm.sh/react@18.3.1";

function applyStacking(data, stackSep) {
  if (!Array.isArray(data) || data.length <= 1) return data;
  const sep = Number.isFinite(Number(stackSep)) ? Number(stackSep) : 0;
  if (sep === 0) return data;
  return data.map((tr, i) => {
    const y = Array.isArray(tr.y) ? tr.y : null;
    if (!y) return tr;
    return { ...tr, y: y.map((v) => (Number.isFinite(Number(v)) ? Number(v) + i * sep : v)) };
  });
}

function styleGhostTrace(tr) {
  const line = tr.line && typeof tr.line === "object" ? tr.line : {};
  return {
    ...tr,
    opacity: 0.25,
    line: { ...line, width: Math.max(1, Number(line.width || 2) - 1) },
    hoverinfo: "skip",
    showlegend: false,
  };
}

export function PlotlyWrapper({ figure, previousFigure, plotStyle, ghostOverlayEnabled }) {
  const divRef = React.useRef(null);

  React.useEffect(() => {
    const el = divRef.current;
    if (!el || typeof Plotly === "undefined") return;

    if (!figure) {
      Plotly.purge(el);
      return;
    }

    const mode = plotStyle?.mode === "stack" ? "stack" : "overlay";
    const stackSep = plotStyle?.stackSep ?? 0;

    const prevData = ghostOverlayEnabled && previousFigure?.data ? previousFigure.data.map(styleGhostTrace) : [];
    const curData = Array.isArray(figure.data) ? figure.data : [];
    const combinedData = mode === "stack" ? applyStacking([...prevData, ...curData], stackSep) : [...prevData, ...curData];
    const layout = figure.layout || {};

    Plotly.react(el, combinedData, layout, { responsive: true });
  }, [figure, previousFigure, plotStyle, ghostOverlayEnabled]);

  return React.createElement("div", { ref: divRef, className: "plot" });
}

