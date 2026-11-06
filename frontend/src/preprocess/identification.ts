/** X2: element / chemical-state markers drawn on the Prepare plots, region parsing and survey region windows. */

import type { LineMarker, ReferenceMarkerGroup, RegionWindow, SurveyPeak } from "./api";

export type PlotMarker = {
  kind: "ref" | "line" | "peak";
  label: string;
  x: number;
  /** Optional band (min-max of the library energies). */
  x0?: number;
  x1?: number;
  color: string;
  /** Hover text. */
  detail?: string;
};

export const MARKER_COLORS = ["#c0392b", "#2980b9", "#27ae60", "#8e44ad", "#d35400", "#16a085", "#7f8c8d", "#f39c12"];

type Fig = { data?: unknown[]; layout?: Record<string, any>; kind?: string; figures?: Fig[] } | null | undefined;

/**
 * Add the markers to a Plotly figure as vertical guides (shapes + labels) on the MAIN panel (``y domain``), so they
 * also work on the fit figure whose residual panel sits below. Returns the same object when there are no markers.
 */
export function applyMarkers<T extends Fig>(fig: T, markers: PlotMarker[]): T {
  if (!fig || !markers.length) return fig;
  if (fig.kind === "fit_stack" && Array.isArray(fig.figures)) {
    return { ...fig, figures: fig.figures.map((f) => applyMarkers(f, markers)) } as T;
  }
  if (!fig.layout) return fig;
  const shapes: Record<string, unknown>[] = [...((fig.layout.shapes as Record<string, unknown>[]) ?? [])];
  const annotations: Record<string, unknown>[] = [...((fig.layout.annotations as Record<string, unknown>[]) ?? [])];
  markers.forEach((m, i) => {
    if (m.x0 != null && m.x1 != null && m.x1 > m.x0) {
      shapes.push({
        type: "rect",
        xref: "x",
        yref: "y domain",
        x0: m.x0,
        x1: m.x1,
        y0: 0,
        y1: 1,
        fillcolor: m.color,
        opacity: 0.1,
        line: { width: 0 },
        layer: "below",
      });
    }
    shapes.push({
      type: "line",
      xref: "x",
      yref: "y domain",
      x0: m.x,
      x1: m.x,
      y0: 0,
      y1: 1,
      line: { color: m.color, width: m.kind === "peak" ? 1 : 1.5, dash: m.kind === "line" ? "dot" : "solid" },
    });
    annotations.push({
      xref: "x",
      yref: "y domain",
      x: m.x,
      y: 1,
      yanchor: "bottom",
      text: m.label,
      showarrow: false,
      textangle: m.kind === "line" ? -90 : 0,
      yshift: m.kind === "line" ? 0 : 12 * (i % 3),
      font: { size: 10, color: m.color },
      hovertext: m.detail,
    });
  });
  return { ...fig, layout: { ...fig.layout, shapes, annotations } } as T;
}

/** Element + line from an XPS region name: "Co2pspectrum1", "Co 2p", "W4f", "O1s_1". Null when none is recognised. */
export function parseRegionLine(region: string | null | undefined): { element: string; line: string } | null {
  const m = /^\s*([A-Z][a-z]?)\s*([1-7][spdf])/.exec(String(region ?? ""));
  return m ? { element: m[1]!, line: m[2]! } : null;
}

/** The library line to use for a region line: exact, else the first with the same shell (2p -> 2p3/2). */
export function pickLibraryLine(lines: string[], wanted: string | null | undefined): string | null {
  if (!lines.length) return null;
  if (wanted) {
    const exact = lines.find((l) => l.toLowerCase() === wanted.toLowerCase());
    if (exact) return exact;
    const shell = lines.find((l) => l.toLowerCase().startsWith(wanted.toLowerCase()));
    if (shell) return shell;
  }
  return lines[0] ?? null;
}

/** Marker for one chemical-state group: median energy with the min-max band of the library entries. */
export function referenceMarker(g: ReferenceMarkerGroup, color: string): PlotMarker {
  return {
    kind: "ref",
    label: g.compound,
    x: g.median_eV,
    x0: g.max_eV > g.min_eV ? g.min_eV : undefined,
    x1: g.max_eV > g.min_eV ? g.max_eV : undefined,
    color,
    detail: `${g.compound} ${g.line}: median ${g.median_eV.toFixed(2)} eV (${g.min_eV.toFixed(2)}–${g.max_eV.toFixed(2)}, ${g.n_entries} entries; ${g.provenance.join(", ") || "n/a"})`,
  };
}

export function lineMarker(m: LineMarker): PlotMarker {
  return {
    kind: "line",
    label: m.label + (m.kind === "auger" ? " (Auger)" : ""),
    x: m.be_eV,
    color: m.kind === "auger" ? "#8e44ad" : "#2c3e50",
    detail: `${m.label}: ${m.be_eV.toFixed(1)} eV (${m.basis === "elemental" ? "elemental" : "median of compounds, range " + m.be_min_eV.toFixed(1) + "–" + m.be_max_eV.toFixed(1)})`,
  };
}

export type PeakRow = { peak: SurveyPeak; match: SurveyPeak["match"]; include: boolean };

/** Region windows (centre = the measured peak, +- half width) for the included, matched peaks; windows are not merged. */
export function windowsFromPeaks(rows: PeakRow[], halfWidth: number): RegionWindow[] {
  const out: RegionWindow[] = [];
  for (const r of rows) {
    if (!r.include || !r.match) continue;
    out.push({
      label: r.match.label,
      element: r.match.element,
      line: r.match.line,
      be_eV: r.peak.be_eV,
      be_min_eV: r.peak.be_eV - halfWidth,
      be_max_eV: r.peak.be_eV + halfWidth,
    });
  }
  return out;
}

/** Standard 18-column periodic table (lanthanides / actinides on their own rows). */
export const PERIODIC_ROWS: string[][] = [
  ["H", ...Array(16).fill(""), "He"],
  ["Li", "Be", ...Array(10).fill(""), "B", "C", "N", "O", "F", "Ne"],
  ["Na", "Mg", ...Array(10).fill(""), "Al", "Si", "P", "S", "Cl", "Ar"],
  ["K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr"],
  ["Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe"],
  ["Cs", "Ba", "La", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn"],
  ["", "", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Th", "U"],
];

/** x range of the first plain trace of a figure (for requesting markers in view). */
export function figureXRange(fig: Fig): [number, number] | null {
  const traces: any[] =
    fig?.kind === "fit_stack" ? ((fig.figures?.[0]?.data as any[]) ?? []) : ((fig?.data as any[]) ?? []);
  let lo = Infinity;
  let hi = -Infinity;
  for (const t of traces) {
    const xs: unknown = t?.x;
    if (!Array.isArray(xs)) continue;
    for (const v of xs) {
      const n = Number(v);
      if (Number.isFinite(n)) {
        if (n < lo) lo = n;
        if (n > hi) hi = n;
      }
    }
  }
  return Number.isFinite(lo) && hi > lo ? [lo, hi] : null;
}

/** First plain (x, y) trace of a figure, ascending or descending, for survey peak detection. */
export function figureFirstSpectrum(fig: Fig): { x: number[]; y: number[] } | null {
  const traces: any[] =
    fig?.kind === "fit_stack" ? ((fig.figures?.[0]?.data as any[]) ?? []) : ((fig?.data as any[]) ?? []);
  for (const t of traces) {
    if (Array.isArray(t?.x) && Array.isArray(t?.y) && t.x.length === t.y.length && t.x.length >= 10) {
      const x = t.x.map(Number);
      const y = t.y.map(Number);
      if (x.every(Number.isFinite) && y.every(Number.isFinite)) return { x, y };
    }
  }
  return null;
}
