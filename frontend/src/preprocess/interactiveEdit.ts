/**
 * X1b: structural edits of the fitting model from the interactive preview: add backgrounds (seeded from the data),
 * draggable background levels, satellites tied to a peak, moving a recipe group together, tying / fixing parameters
 * and deleting components. Pure functions on the editor params so they can be unit-tested.
 */

import { gapNumber } from "./fitResidualPlot";
import {
  defaultRowsForComponent,
  isPeakComponentType,
  uniqueComponentIdAgainst,
  upsertParamLink,
  type FittingComponentEditor,
  type FittingEditorParams,
  type FittingParamLink,
  type FittingParamRow,
} from "./fittingUtils";
import { adoptDisplayedParams, isFollower, type FitMeta } from "./interactiveFit";

/** Backgrounds that REPLACE each other (one baseline under the peaks); erfc steps and SB are additive. */
export const BASELINE_LIKE = new Set([
  "shirley_bg",
  "tougaard_bg",
  "tougaard_u4_bg",
  "slope_bg",
  "linear_bg",
  "polynomial_background",
]);

export type BackgroundChoice = { type: string; label: string; hint: string; refit: boolean };

export const BACKGROUND_CHOICES: BackgroundChoice[] = [
  { type: "shirley_bg", label: "Shirley", hint: "Step that follows the peak area; the fit scales it. Drag its end levels.", refit: true },
  { type: "linear_bg", label: "Linear", hint: "Straight line between two end levels. Drag the end handles.", refit: false },
  { type: "tougaard_u4_bg", label: "Tougaard (with T0)", hint: "Universal cross-section with a band-gap onset. Edit B, C, D, T0 in the card.", refit: true },
  { type: "tougaard_bg", label: "Tougaard (classic)", hint: "Tougaard with the extend option.", refit: true },
  { type: "slope_bg", label: "Slope", hint: "Sloping baseline scaled by the fit.", refit: true },
  { type: "erfc_step_bg", label: "erfc step / edge", hint: "Fermi edge or a step under the peaks. Drag its position, height and width.", refit: false },
  { type: "shirley_of_bg", label: "Shirley of a peak (SB)", hint: "Shirley step of one chosen peak.", refit: true },
  { type: "polynomial_background", label: "Polynomial", hint: "Polynomial baseline (degree 1 here; raise it in the card).", refit: true },
];

const SHORT_ID: Record<string, string> = {
  shirley_bg: "shirley",
  linear_bg: "linear",
  tougaard_u4_bg: "tougaard",
  tougaard_bg: "tougaard",
  slope_bg: "slope",
  erfc_step_bg: "erfc",
  shirley_of_bg: "sb",
  polynomial_background: "poly",
};

function ids(fp: FittingEditorParams): Set<string> {
  return new Set(fp.components.map((c) => String(c.component_id ?? "").toLowerCase()).filter(Boolean));
}

/** Drop links that mention a removed component (as follower or driver, or inside an expression). */
function dropLinksOf(links: FittingParamLink[] | undefined, id: string): FittingParamLink[] {
  return (links ?? []).filter(
    (l) =>
      l.source_component_id !== id &&
      l.target_component_id !== id &&
      !(l.mode === "expr" && (l.expr ?? "").includes(`{${id}.`))
  );
}

/** Mean data level near both ends of the fit window (3 points each side). */
export function windowEndLevels(meta: FitMeta): { xlo: number; xhi: number; lo: number; hi: number } {
  const pts: Array<[number, number]> = [];
  for (let i = 0; i < meta.x.length; i++) {
    const x = meta.x[i]!;
    if (meta.fitMin != null && x < meta.fitMin) continue;
    if (meta.fitMax != null && x > meta.fitMax) continue;
    const y = meta.y[i]!;
    if (Number.isFinite(x) && Number.isFinite(y)) pts.push([x, y]);
  }
  pts.sort((a, b) => a[0] - b[0]);
  const k = Math.max(1, Math.min(3, Math.floor(pts.length / 4)));
  const mean = (s: Array<[number, number]>) => s.reduce((a, p) => a + p[1], 0) / Math.max(1, s.length);
  return {
    xlo: pts[0]?.[0] ?? 0,
    xhi: pts[pts.length - 1]?.[0] ?? 0,
    lo: mean(pts.slice(0, k)),
    hi: mean(pts.slice(-k)),
  };
}

export type AddBackgroundResult = { fp: FittingEditorParams; component_id: string; replaced: string | null; needsRefit: boolean };

/** Add an active background; a baseline-like one replaces the current baseline. Linear and erfc are seeded from the data ends. */
export function addBackground(
  fp0: FittingEditorParams,
  meta: FitMeta,
  catalog: Parameters<typeof defaultRowsForComponent>[2],
  type: string,
  opts: { sbSource?: string | null; degree?: number } = {}
): AddBackgroundResult {
  const fp = adoptDisplayedParams(fp0, meta);
  let components = fp.components.slice();
  let links = fp.param_links;
  let replaced: string | null = null;
  if (BASELINE_LIKE.has(type)) {
    const idx = components.findIndex((c) => BASELINE_LIKE.has(String(c.component_type)));
    if (idx >= 0) {
      replaced = components[idx]!.component_id;
      links = dropLinksOf(links, replaced);
      components = components.filter((_, i) => i !== idx);
    }
  }
  const used = new Set(components.map((c) => String(c.component_id ?? "").toLowerCase()).filter(Boolean));
  const id = uniqueComponentIdAgainst(SHORT_ID[type] ?? "bg", used);
  const degree = type === "polynomial_background" ? Math.max(1, Math.round(opts.degree ?? 1)) : 0;
  const lv = windowEndLevels(meta);
  const rows = defaultRowsForComponent(type as never, degree, catalog).map((r) => {
    if (type === "linear_bg") {
      if (r.key === "low") return { ...r, p0: lv.lo, vary: false };
      if (r.key === "high") return { ...r, p0: lv.hi, vary: false };
    }
    if (type === "erfc_step_bg") {
      if (r.key === "const") return { ...r, p0: lv.lo };
      if (r.key === "height") return { ...r, p0: lv.hi - lv.lo };
      if (r.key === "pos") return { ...r, p0: (lv.xlo + lv.xhi) / 2 };
    }
    if (type === "shirley_bg" && r.key === "const") return { ...r, p0: Math.min(lv.lo, lv.hi) };
    return r;
  });
  const comp: FittingComponentEditor = {
    component_id: id,
    component_type: type as never,
    degree,
    rows,
    ...(type === "shirley_of_bg" && opts.sbSource ? { options: { of: opts.sbSource } } : {}),
  };
  const next = BASELINE_LIKE.has(type) ? [comp, ...components] : [...components, comp];
  const choice = BACKGROUND_CHOICES.find((c) => c.type === type);
  return { fp: { ...fp, components: next, param_links: links }, component_id: id, replaced, needsRefit: choice?.refit ?? false };
}

// ------------------------------------------------------------------------------------------------ background handles

export type BgHandle = {
  key: string;
  component_id: string;
  ci: number;
  kind: "lo" | "hi" | "const-end" | "step-end" | "edge" | "edge-width";
  x: number;
  y: number;
  /** Short hover text. */
  title: string;
  canEdit: boolean;
};

function curveAt(y: Array<number | null> | null | undefined, x: number[], at: number): number | null {
  if (!y) return null;
  let best = -1;
  let bd = Infinity;
  for (let i = 0; i < x.length; i++) {
    if (!Number.isFinite(gapNumber(y[i]))) continue;
    const d = Math.abs(x[i]! - at);
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return best >= 0 ? gapNumber(y[best]) : null;
}

/** Handles on the drawn backgrounds: linear ends, Shirley end levels, erfc position / height / width. */
export function backgroundHandles(meta: FitMeta, fp: FittingEditorParams): BgHandle[] {
  const out: BgHandle[] = [];
  const lv = windowEndLevels(meta);
  fp.components.forEach((c, ci) => {
    const mc = meta.components.find((m) => m.component_id === c.component_id);
    if (!mc) return;
    const p = mc.params;
    const free = (key: string) => !isFollower(fp, c.component_id, key);
    if (c.component_type === "linear_bg" && Number.isFinite(p.low) && Number.isFinite(p.high)) {
      out.push({ key: `${c.component_id}:lo`, component_id: c.component_id, ci, kind: "lo", x: lv.xlo, y: p.low!, title: `${c.component_id}: low-x end level`, canEdit: free("low") });
      out.push({ key: `${c.component_id}:hi`, component_id: c.component_id, ci, kind: "hi", x: lv.xhi, y: p.high!, title: `${c.component_id}: high-x end level`, canEdit: free("high") });
    } else if (c.component_type === "shirley_bg" && mc.y_hat && Number.isFinite(p.const)) {
      const yLo = curveAt(mc.y_hat, meta.x, lv.xlo);
      const yHi = curveAt(mc.y_hat, meta.x, lv.xhi);
      if (yLo != null && yHi != null) {
        const loIsConst = Math.abs(yLo - p.const!) <= Math.abs(yHi - p.const!);
        out.push({
          key: `${c.component_id}:const`,
          component_id: c.component_id,
          ci,
          kind: "const-end",
          x: loIsConst ? lv.xlo : lv.xhi,
          y: loIsConst ? yLo : yHi,
          title: `${c.component_id}: base level (const)`,
          canEdit: free("const"),
        });
        out.push({
          key: `${c.component_id}:step`,
          component_id: c.component_id,
          ci,
          kind: "step-end",
          x: loIsConst ? lv.xhi : lv.xlo,
          y: loIsConst ? yHi : yLo,
          title: `${c.component_id}: step height (scales k)`,
          canEdit: free("k"),
        });
      }
    } else if (c.component_type === "erfc_step_bg" && Number.isFinite(p.pos) && Number.isFinite(p.height) && Number.isFinite(p.const)) {
      const mid = p.const! + p.height! / 2;
      out.push({ key: `${c.component_id}:edge`, component_id: c.component_id, ci, kind: "edge", x: p.pos!, y: mid, title: `${c.component_id}: step position and height`, canEdit: free("pos") || free("height") });
      out.push({ key: `${c.component_id}:ew`, component_id: c.component_id, ci, kind: "edge-width", x: p.pos! + (p.fwhm ?? 0.5), y: mid, title: `${c.component_id}: edge width`, canEdit: free("fwhm") });
    }
  });
  return out;
}

function setRowP0(fp: FittingEditorParams, ci: number, key: string, v: number): FittingEditorParams {
  const comp = fp.components[ci]!;
  const ri = comp.rows.findIndex((r) => r.key === key);
  if (ri < 0) return fp;
  const row = comp.rows[ri]!;
  let val = v;
  if (typeof row.lower === "number") val = Math.max(val, row.lower);
  if (typeof row.upper === "number") val = Math.min(val, row.upper);
  const rows = comp.rows.slice();
  rows[ri] = { ...row, p0: val };
  const components = fp.components.slice();
  components[ci] = { ...comp, rows };
  return { ...fp, components };
}

/** Apply a background handle drag. Dragging a fixed level sets that fixed value (an explicit placement). */
export function dragBackground(fp0: FittingEditorParams, meta: FitMeta, h: BgHandle, to: { x: number; y: number }): FittingEditorParams {
  if (!h.canEdit) return fp0;
  const fp = adoptDisplayedParams(fp0, meta);
  const mc = meta.components.find((m) => m.component_id === h.component_id);
  if (!mc) return fp;
  const p = mc.params;
  switch (h.kind) {
    case "lo":
      return setRowP0(fp, h.ci, "low", to.y);
    case "hi":
      return setRowP0(fp, h.ci, "high", to.y);
    case "const-end":
      return setRowP0(fp, h.ci, "const", to.y);
    case "step-end": {
      const cur = Math.abs(h.y - (p.const ?? 0));
      const want = Math.abs(to.y - (p.const ?? 0));
      return cur > 1e-9 && Number.isFinite(p.k) ? setRowP0(fp, h.ci, "k", p.k! * (want / cur)) : fp;
    }
    case "edge": {
      let next = setRowP0(fp, h.ci, "pos", to.x);
      next = setRowP0(next, h.ci, "height", 2 * (to.y - (p.const ?? 0)));
      return next;
    }
    case "edge-width":
      return setRowP0(fp, h.ci, "fwhm", Math.max(1e-3, Math.abs(to.x - (p.pos ?? 0))));
  }
}

// ------------------------------------------------------------------------------------------------ satellites and groups

const areaOf = (meta: FitMeta, id: string): number | null => {
  const a = meta.components.find((m) => m.component_id === id)?.area;
  return typeof a === "number" && Number.isFinite(a) && a > 0 ? a : null;
};

/**
 * Add a satellite (shake-up) peak tied to ``parent``: position = parent + ``offset`` and area = ``ratio`` x parent area.
 * The new peak copies the parent's shape and width; both ties are editable in the card.
 */
export function addSatellite(
  fp0: FittingEditorParams,
  meta: FitMeta,
  parentCi: number,
  opts: { offset: number; ratio: number }
): { fp: FittingEditorParams; component_id: string } {
  const fp = adoptDisplayedParams(fp0, meta);
  const parent = fp.components[parentCi];
  if (!parent || !isPeakComponentType(String(parent.component_type))) throw new Error("select a peak to add a satellite to");
  if (!(opts.ratio > 0)) throw new Error("area ratio must be positive");
  const id = uniqueComponentIdAgainst(`${parent.component_id}_sat`, ids(fp));
  const posRow = parent.rows.find((r) => r.key === "pos");
  const ampRow = parent.rows.find((r) => r.key === "amp");
  const comp: FittingComponentEditor = {
    ...parent,
    component_id: id,
    options: undefined,
    rows: parent.rows.map((r) => {
      if (r.key === "pos") return { ...r, p0: (posRow?.p0 ?? 0) + opts.offset, vary: true, auto: false, lower: null, upper: null };
      if (r.key === "amp") return { ...r, p0: (ampRow?.p0 ?? 1) * opts.ratio, vary: true, auto: false };
      return { ...r };
    }),
  };
  let links = upsertParamLink(fp.param_links, { source_component_id: id, source_key: "pos", target_component_id: parent.component_id, target_key: "pos", mode: "offset", offset: opts.offset }, id, "pos");
  links = upsertParamLink(links, { source_component_id: id, source_key: "amp", target_component_id: parent.component_id, target_key: "amp", mode: "area_ratio", ratio: opts.ratio }, id, "amp");
  return { fp: { ...fp, components: [...fp.components, comp], param_links: links }, component_id: id };
}

/** Groups that move together: recipe-loaded multiplets (two or more peaks of one recipe). */
export function recipeGroups(fp: FittingEditorParams): Array<{ id: string; members: string[] }> {
  const present = new Set(fp.components.map((c) => c.component_id));
  return Object.entries(fp.recipe_components ?? {})
    .map(([id, members]) => ({ id, members: members.filter((m) => present.has(m)) }))
    .filter((g) => g.members.length >= 2);
}

/** Shift the position (and position bounds) of every peak of a group by ``dx``. */
export function shiftGroup(fp0: FittingEditorParams, meta: FitMeta, members: string[], dx: number): FittingEditorParams {
  const fp = adoptDisplayedParams(fp0, meta);
  const set = new Set(members);
  const components = fp.components.map((c) => {
    if (!set.has(c.component_id)) return c;
    return {
      ...c,
      rows: c.rows.map((r) =>
        r.key === "pos"
          ? { ...r, p0: r.p0 + dx, lower: typeof r.lower === "number" ? r.lower + dx : r.lower, upper: typeof r.upper === "number" ? r.upper + dx : r.upper }
          : r
      ),
    };
  });
  return { ...fp, components };
}

/** Anchor for a group handle: the member whose drawn curve is highest. */
export function groupAnchor(meta: FitMeta, members: string[]): { x: number; top: number } | null {
  let best: { x: number; top: number } | null = null;
  for (const id of members) {
    const mc = meta.components.find((m) => m.component_id === id);
    if (!mc?.y_hat) continue;
    for (let i = 0; i < mc.y_hat.length; i++) {
      const v = gapNumber(mc.y_hat[i]);
      if (Number.isFinite(v) && (best == null || v > best.top)) best = { x: meta.x[i]!, top: v };
    }
  }
  return best;
}

// ------------------------------------------------------------------------------------------------ inspector edits

export function setRowField(
  fp0: FittingEditorParams,
  meta: FitMeta | undefined,
  ci: number,
  key: string,
  patch: Partial<Pick<FittingParamRow, "p0" | "vary" | "lower" | "upper" | "auto">>
): FittingEditorParams {
  const fp = meta ? adoptDisplayedParams(fp0, meta) : fp0;
  const comp = fp.components[ci];
  if (!comp) return fp;
  const ri = comp.rows.findIndex((r) => r.key === key);
  if (ri < 0) return fp;
  const rows = comp.rows.slice();
  rows[ri] = { ...rows[ri]!, ...patch };
  const components = fp.components.slice();
  components[ci] = { ...comp, rows };
  return { ...fp, components };
}

export type TieMode = "none" | "equal" | "offset" | "area_ratio";

/** Current tie of a parameter as (mode, driver component, value). */
export function tieOf(fp: FittingEditorParams, componentId: string, key: string): { mode: TieMode; driver: string; value: number | null } {
  const l = (fp.param_links ?? []).find((q) => q.source_component_id === componentId && q.source_key === key && q.mode !== "expr");
  if (!l) return { mode: "none", driver: "", value: null };
  if (l.mode === "offset") return { mode: "offset", driver: l.target_component_id, value: l.offset ?? 0 };
  if (l.mode === "area_ratio") return { mode: "area_ratio", driver: l.target_component_id, value: l.ratio ?? 1 };
  return { mode: "equal", driver: l.target_component_id, value: null };
}

/** True when the parameter is defined by an expression link (not editable here). */
export function hasExpression(fp: FittingEditorParams, componentId: string, key: string): boolean {
  return (fp.param_links ?? []).some((l) => l.mode === "expr" && l.source_component_id === componentId && l.source_key === key);
}

/** Tie ``componentId.key`` to the same parameter of ``driver``. Defaults for offset / ratio come from the drawn values. */
export function tieParam(
  fp0: FittingEditorParams,
  meta: FitMeta | undefined,
  componentId: string,
  key: string,
  mode: TieMode,
  driver: string,
  value?: number | null
): FittingEditorParams {
  const fp = meta ? adoptDisplayedParams(fp0, meta) : fp0;
  if (mode === "none" || !driver) return { ...fp, param_links: upsertParamLink(fp.param_links, null, componentId, key) };
  const row = (id: string) => fp.components.find((c) => c.component_id === id)?.rows.find((r) => r.key === key);
  let link: FittingParamLink = { source_component_id: componentId, source_key: key, target_component_id: driver, target_key: key, mode };
  if (mode === "offset") {
    const d = (row(componentId)?.p0 ?? 0) - (row(driver)?.p0 ?? 0);
    link = { ...link, offset: value != null && Number.isFinite(value) ? value : d };
  } else if (mode === "area_ratio") {
    const a = meta ? areaOf(meta, componentId) : null;
    const b = meta ? areaOf(meta, driver) : null;
    link = { ...link, ratio: value != null && Number.isFinite(value) && value > 0 ? value : a != null && b != null ? a / b : 1 };
  }
  return { ...fp, param_links: upsertParamLink(fp.param_links, link, componentId, key) };
}

/** Candidate drivers for a tie: other components that have the same parameter and do not already follow this one. */
export function tieCandidates(fp: FittingEditorParams, componentId: string, key: string): string[] {
  const follows = (a: string, b: string): boolean => {
    // true when a (transitively) follows b
    const seen = new Set<string>();
    const stack = [a];
    while (stack.length) {
      const cur = stack.pop()!;
      if (cur === b) return true;
      if (seen.has(cur)) continue;
      seen.add(cur);
      for (const l of fp.param_links ?? []) {
        if (l.source_component_id === cur) {
          if (l.mode === "expr") for (const m of (l.expr ?? "").matchAll(/\{([^.{}]+)\./g)) stack.push(m[1]!);
          else stack.push(l.target_component_id);
        }
      }
    }
    return false;
  };
  return fp.components
    .filter((c) => c.component_id !== componentId && c.rows.some((r) => r.key === key) && !follows(c.component_id, componentId))
    .map((c) => c.component_id);
}

export function deleteComponent(fp0: FittingEditorParams, ci: number): FittingEditorParams {
  const comp = fp0.components[ci];
  if (!comp) return fp0;
  const id = comp.component_id;
  const rc = Object.fromEntries(
    Object.entries(fp0.recipe_components ?? {}).map(([k, v]) => [k, v.filter((m) => m !== id)])
  );
  return {
    ...fp0,
    components: fp0.components.filter((_, i) => i !== ci),
    param_links: dropLinksOf(fp0.param_links, id),
    recipe_components: rc,
  };
}
