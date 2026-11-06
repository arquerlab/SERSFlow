/**
 * X1 interactive fitting: pure logic behind dragging peaks on the fitting preview.
 *
 * Handles sit on the DRAWN model (``FitMeta``, the last fit or evaluation) and edits are written back as initial
 * values (``p0``) of the fitting step. Constraints are respected: fixed parameters and followers of a link or
 * expression have no handle, and a dragged value is clipped to its own bounds.
 */

import { gapNumber, isBackgroundComponentType, sumBackgroundY, type FitPlotComponent } from "./fitResidualPlot";
import {
  defaultRowsForComponent,
  isPeakComponentType,
  uniqueComponentIdAgainst,
  type FittingComponentEditor,
  type FittingEditorParams,
  type FittingParamRow,
} from "./fittingUtils";
import type { FitRequest } from "./api";
import { inlineTarget, type FitPreviewInput } from "./fitInputs";

/** What the preview currently draws for one spectrum. */
export type FitMeta = {
  x: number[];
  y: number[];
  yHat: Array<number | null>;
  residual: Array<number | null>;
  components: Array<FitPlotComponent & { params: Record<string, number> }>;
  /** True when the curve came from an optimiser run, false for an evaluation of edited parameters. */
  fitted: boolean;
  fitMin: number | null;
  fitMax: number | null;
  xAxisTitle: string;
};

export type PeakHandle = {
  component_id: string;
  ci: number;
  color: string;
  /** Curve maximum (data coordinates). */
  xMax: number;
  top: number;
  height: number;
  baseline: number;
  /** Half-maximum point on one flank (null when the curve never falls to half height inside the window). */
  halfX: number | null;
  halfY: number;
  posRow: number;
  ampRow: number;
  fwhmRow: number;
  canMove: boolean;
  canHeight: boolean;
  canWidth: boolean;
};

/** True when the parameter is the DEPENDENT side of a link or expression (it cannot be set directly). */
export function isFollower(fp: FittingEditorParams, componentId: string, key: string): boolean {
  return (fp.param_links ?? []).some((l) => l.source_component_id === componentId && l.source_key === key);
}

function rowIndex(c: FittingComponentEditor, key: string): number {
  return c.rows.findIndex((r) => r.key === key);
}

function editable(fp: FittingEditorParams, c: FittingComponentEditor, ri: number): boolean {
  if (ri < 0) return false;
  const row = c.rows[ri]!;
  if (row.vary === false) return false;
  return !isFollower(fp, c.component_id, row.key);
}

/** Peak colours in plot order (same assignment as the fit figure). */
const COLORS = ["#e67e22", "#3498db", "#9b59b6", "#1abc9c", "#e74c3c", "#f39c12", "#2ecc71"];

export function peakHandles(meta: FitMeta, fp: FittingEditorParams): PeakHandle[] {
  const n = meta.x.length;
  const { bgSum } = sumBackgroundY(meta.components, n);
  const out: PeakHandle[] = [];
  let colorIdx = 0;
  fp.components.forEach((c, ci) => {
    if (isBackgroundComponentType(c.component_type) || !isPeakComponentType(c.component_type)) return;
    const color = COLORS[colorIdx % COLORS.length]!;
    colorIdx += 1;
    const mc = meta.components.find((m) => m.component_id === c.component_id);
    const cy = mc?.y_hat;
    if (!cy || cy.length !== n) return;
    let im = -1;
    let best = -Infinity;
    for (let i = 0; i < n; i++) {
      const v = gapNumber(cy[i]);
      if (Number.isFinite(v) && v > best) {
        best = v;
        im = i;
      }
    }
    if (im < 0 || !(best > 0)) return;
    const b = gapNumber(bgSum[im]);
    const baseline = Number.isFinite(b) ? b : 0;
    const half = best / 2;
    let halfX: number | null = null;
    for (const dir of [1, -1]) {
      for (let i = im + dir; i >= 0 && i < n; i += dir) {
        const v = gapNumber(cy[i]);
        if (!Number.isFinite(v)) break;
        if (v <= half) {
          const prev = gapNumber(cy[i - dir]);
          const t = prev > v ? (prev - half) / (prev - v) : 0;
          halfX = meta.x[i - dir]! + t * (meta.x[i]! - meta.x[i - dir]!);
          break;
        }
      }
      if (halfX != null) break;
    }
    const posRow = rowIndex(c, "pos");
    const ampRow = rowIndex(c, "amp");
    const fwhmRow = rowIndex(c, "fwhm");
    out.push({
      component_id: c.component_id,
      ci,
      color,
      xMax: meta.x[im]!,
      top: baseline + best,
      height: best,
      baseline,
      halfX,
      halfY: baseline + half,
      posRow,
      ampRow,
      fwhmRow,
      canMove: editable(fp, c, posRow),
      canHeight: editable(fp, c, ampRow),
      canWidth: halfX != null && editable(fp, c, fwhmRow),
    });
  });
  return out;
}

function clip(v: number, row: FittingParamRow): number {
  let out = v;
  if (typeof row.lower === "number" && Number.isFinite(row.lower)) out = Math.max(out, row.lower);
  if (typeof row.upper === "number" && Number.isFinite(row.upper)) out = Math.min(out, row.upper);
  return out;
}

function setRow(fp: FittingEditorParams, ci: number, ri: number, patch: Partial<FittingParamRow>): FittingEditorParams {
  const components = fp.components.slice();
  const comp = components[ci]!;
  const rows = comp.rows.slice();
  rows[ri] = { ...rows[ri]!, ...patch };
  components[ci] = { ...comp, rows };
  return { ...fp, components };
}

/** Baseline (sum of background components) interpolated at ``x``; 0 without a background. */
export function baselineAt(meta: FitMeta, x: number): number {
  const n = meta.x.length;
  const { bgSum } = sumBackgroundY(meta.components, n);
  let best = -1;
  let bd = Infinity;
  for (let i = 0; i < n; i++) {
    const d = Math.abs(meta.x[i]! - x);
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  const b = best >= 0 ? gapNumber(bgSum[best]) : Number.NaN;
  return Number.isFinite(b) ? b : 0;
}

/**
 * Adopt the DRAWN parameters of the last fit as initial values of every row, so an edit starts from what the user
 * sees (not from the previous seeds). Amplitude Auto is switched off for the adopted rows. A no-op when the figure
 * already came from an evaluation of the editor's own values.
 */
export function adoptDisplayedParams(fp: FittingEditorParams, meta: FitMeta): FittingEditorParams {
  if (!meta.fitted) return fp;
  const components = fp.components.map((c) => {
    const mc = meta.components.find((m) => m.component_id === c.component_id);
    if (!mc) return c;
    const rows = c.rows.map((r) => {
      const v = mc.params[r.key];
      if (typeof v !== "number" || !Number.isFinite(v)) return r;
      return { ...r, p0: v, ...(r.auto ? { auto: false } : {}) };
    });
    return { ...c, rows };
  });
  return { ...fp, components };
}

export type DragKind = "move" | "width";

/**
 * Apply a handle drag to the editor params. ``move``: x sets the position (shifted by the drag distance), y sets the
 * peak height above the baseline (amplitude scales in proportion). ``width``: the half-maximum handle sets the FWHM
 * in proportion to its distance from the peak maximum. Locked parameters are left alone; values are clipped to bounds.
 */
export function dragPeak(
  fp0: FittingEditorParams,
  meta: FitMeta,
  h: PeakHandle,
  kind: DragKind,
  to: { x: number; y: number }
): FittingEditorParams {
  let fp = adoptDisplayedParams(fp0, meta);
  const comp = fp.components[h.ci];
  const mc = meta.components.find((m) => m.component_id === h.component_id);
  if (!comp || !mc) return fp;
  if (kind === "move") {
    if (h.canMove && h.posRow >= 0) {
      const cur = mc.params[comp.rows[h.posRow]!.key];
      if (typeof cur === "number") {
        fp = setRow(fp, h.ci, h.posRow, { p0: clip(cur + (to.x - h.xMax), comp.rows[h.posRow]!) });
      }
    }
    if (h.canHeight && h.ampRow >= 0) {
      const cur = mc.params[comp.rows[h.ampRow]!.key];
      const target = to.y - baselineAt(meta, to.x);
      if (typeof cur === "number" && h.height > 0 && target > 0) {
        fp = setRow(fp, h.ci, h.ampRow, { p0: clip(cur * (target / h.height), comp.rows[h.ampRow]!), auto: false });
      }
    }
    return fp;
  }
  if (h.canWidth && h.fwhmRow >= 0 && h.halfX != null) {
    const cur = mc.params[comp.rows[h.fwhmRow]!.key];
    const d0 = Math.abs(h.halfX - h.xMax);
    const d1 = Math.abs(to.x - h.xMax);
    if (typeof cur === "number" && d0 > 0 && d1 > 0) {
      fp = setRow(fp, h.ci, h.fwhmRow, { p0: clip(cur * (d1 / d0), comp.rows[h.fwhmRow]!) });
    }
  }
  return fp;
}

/** Fit-window edge drag (``fit_min_x`` / ``fit_max_x``); the two edges never cross. */
export function setWindowEdge(fp: FittingEditorParams, meta: FitMeta, edge: "min" | "max", x: number): FittingEditorParams {
  const lo = Math.min(...meta.x);
  const hi = Math.max(...meta.x);
  const curMin = typeof fp.fit_min_x === "number" ? fp.fit_min_x : lo;
  const curMax = typeof fp.fit_max_x === "number" ? fp.fit_max_x : hi;
  const step = Math.abs(meta.x[1]! - meta.x[0]!) || 0;
  if (edge === "min") return { ...fp, fit_min_x: Math.max(lo, Math.min(x, curMax - 2 * step)) };
  return { ...fp, fit_max_x: Math.min(hi, Math.max(x, curMin + 2 * step)) };
}

/** Whole window set at once (box selection). */
export function setWindow(fp: FittingEditorParams, meta: FitMeta, a: number, b: number): FittingEditorParams {
  const lo = Math.min(...meta.x);
  const hi = Math.max(...meta.x);
  const x0 = Math.max(lo, Math.min(a, b));
  const x1 = Math.min(hi, Math.max(a, b));
  if (!(x1 > x0)) return fp;
  return { ...fp, fit_min_x: x0, fit_max_x: x1 };
}

/** The point of largest POSITIVE residual (data above model) inside the fit window; null when there is none. */
export function maxResidualPoint(meta: FitMeta): { x: number; residual: number; index: number } | null {
  let best: { x: number; residual: number; index: number } | null = null;
  for (let i = 0; i < meta.x.length; i++) {
    const x = meta.x[i]!;
    if (meta.fitMin != null && x < meta.fitMin) continue;
    if (meta.fitMax != null && x > meta.fitMax) continue;
    const r = gapNumber(meta.residual[i]);
    if (Number.isFinite(r) && r > 0 && (best == null || r > best.residual)) best = { x, residual: r, index: i };
  }
  return best;
}

export type NewPeakShape =
  | { kind: "shape"; componentType: string; fwhm?: number | null; m?: number | null }
  | { kind: "copy"; ci: number };

/**
 * Append a peak at ``x`` with the given height above the baseline. ``ampPerHeight`` converts height to the amplitude
 * parameter for a NEW shape (from an evaluation at unit amplitude); a copy keeps the source's amplitude/height ratio.
 * The new peak is free, bounded by its defaults, and linked to nothing.
 */
export function addPeak(
  fp0: FittingEditorParams,
  meta: FitMeta,
  catalog: Parameters<typeof defaultRowsForComponent>[2],
  at: { x: number; height: number },
  shape: NewPeakShape,
  ampPerHeight: number | null
): { fp: FittingEditorParams; component_id: string } {
  const fp = adoptDisplayedParams(fp0, meta);
  const used = new Set(fp.components.map((c) => String(c.component_id ?? "").toLowerCase()).filter(Boolean));
  const id = uniqueComponentIdAgainst("p", used, { preferAutoP: true });
  let comp: FittingComponentEditor;
  if (shape.kind === "copy") {
    const src = fp.components[shape.ci];
    if (!src) throw new Error("source peak not found");
    const handle = peakHandles(meta, fp).find((h) => h.ci === shape.ci);
    const ampKey = src.rows.find((r) => r.key === "amp");
    const ratio = handle && ampKey && handle.height > 0 ? ampKey.p0 / handle.height : null;
    comp = {
      ...src,
      component_id: id,
      rows: src.rows.map((r) => {
        if (r.key === "pos") return { ...r, p0: at.x, vary: true, auto: false };
        if (r.key === "amp") return { ...r, p0: ratio != null ? ratio * at.height : r.p0, vary: true, auto: false };
        return { ...r };
      }),
    };
  } else {
    const rows = defaultRowsForComponent(shape.componentType as never, 0, catalog).map((r) => {
      if (r.key === "pos") return { ...r, p0: at.x, auto: false };
      if (r.key === "amp") return { ...r, p0: ampPerHeight != null ? ampPerHeight * at.height : at.height, auto: false };
      if (r.key === "fwhm" && typeof shape.fwhm === "number" && shape.fwhm > 0) return { ...r, p0: shape.fwhm };
      if (r.key === "m" && typeof shape.m === "number") return { ...r, p0: shape.m };
      return r;
    });
    comp = { component_id: id, component_type: shape.componentType as never, degree: 0, rows };
  }
  return { fp: { ...fp, components: [...fp.components, comp] }, component_id: id };
}

/** /fitting/fit request for the editor's current values (fit = false evaluates without optimising). */
export function buildFitRequest(
  flat: Record<string, unknown>,
  input: FitPreviewInput,
  opts: { technique: string; weighting?: string; fit: boolean }
): FitRequest {
  const comps = (flat.components as FitRequest["components"]) ?? [];
  return {
    target: inlineTarget(input),
    weighting: (opts.weighting ?? "auto") as FitRequest["weighting"],
    components: comps.map((c) => ({ ...c })),
    p0: flat.p0 as number[],
    bounds: { lower: flat.bounds_lower as (number | null)[], upper: flat.bounds_upper as (number | null)[] },
    return_curve: true,
    initial_guess_mode: "default",
    technique_family: opts.technique as FitRequest["technique_family"],
    vary: Array.isArray(flat.vary) ? (flat.vary as boolean[]) : undefined,
    param_links: Array.isArray(flat.param_links) ? (flat.param_links as FitRequest["param_links"]) : undefined,
    xps_region: typeof flat.xps_region === "string" ? flat.xps_region : undefined,
    fit_min_x: typeof flat.fit_min_x === "number" ? flat.fit_min_x : undefined,
    fit_max_x: typeof flat.fit_max_x === "number" ? flat.fit_max_x : undefined,
    initial_area_ratios:
      typeof flat.initial_area_ratios === "string" && flat.initial_area_ratios.trim() ? flat.initial_area_ratios.trim() : undefined,
    fit: opts.fit,
  };
}
