import type { FittingComponentSpecPublic, FittingParamSpecPublic } from "./api";

export const MAX_POLY_DEGREE = 12;

export const PEAK_COMPONENT_TYPES = [
  "gaussian",
  "lorentzian",
  "pseudo_voigt",
  "gl",
  "voigt",
  "ds",
  "gds",
  "la",
  "lf",
  "a_gl",
  "apv",
  "asymmetric_voigt",
] as const;
export type FittingPeakType = (typeof PEAK_COMPONENT_TYPES)[number];

export const XPS_BG_COMPONENT_TYPES = ["shirley_bg", "tougaard_bg", "slope_bg"] as const;
export type FittingXpsBgType = (typeof XPS_BG_COMPONENT_TYPES)[number];

/** XPS-only lmfitxps models that are not Shirley/Tougaard-style backgrounds. */
export const XPS_SPECIAL_COMPONENT_TYPES = ["fermi_edge"] as const;
export type FittingXpsSpecialType = (typeof XPS_SPECIAL_COMPONENT_TYPES)[number];

/** Prefer catalog `component_type` list; fall back to builtin XPS bg ids. */
export function xpsBgComponentTypesFromCatalog(
  catalog: FittingComponentSpecPublic[] | undefined
): readonly string[] {
  if (!catalog?.length) return XPS_BG_COMPONENT_TYPES;
  const fromCat = catalog
    .map((c) => String(c.component_type || "").trim().toLowerCase())
    .filter((ct) => ct.endsWith("_bg") || XPS_BG_COMPONENT_TYPES.includes(ct as FittingXpsBgType));
  const uniq = [...new Set(fromCat)];
  return uniq.length ? uniq : XPS_BG_COMPONENT_TYPES;
}

export function xpsSpecialComponentTypesFromCatalog(
  catalog: FittingComponentSpecPublic[] | undefined
): readonly string[] {
  if (!catalog?.length) return XPS_SPECIAL_COMPONENT_TYPES;
  const fromCat = catalog
    .map((c) => String(c.component_type || "").trim().toLowerCase())
    .filter((ct) => (XPS_SPECIAL_COMPONENT_TYPES as readonly string[]).includes(ct));
  const uniq = [...new Set(fromCat)];
  return uniq.length ? uniq : XPS_SPECIAL_COMPONENT_TYPES;
}

export function xpsBgTypeLabel(ct: string, catalog: FittingComponentSpecPublic[] | undefined): string {
  const key = ct.trim().toLowerCase();
  const spec = catalog?.find((c) => String(c.component_type || "").trim().toLowerCase() === key);
  if (spec?.display_name) return spec.display_name;
  return XPS_BG_TYPE_LABELS[key as FittingXpsBgType] ?? key;
}

export function xpsSpecialTypeLabel(ct: string, catalog: FittingComponentSpecPublic[] | undefined): string {
  const key = ct.trim().toLowerCase();
  const spec = catalog?.find((c) => String(c.component_type || "").trim().toLowerCase() === key);
  if (spec?.display_name) return spec.display_name;
  return XPS_SPECIAL_TYPE_LABELS[key as FittingXpsSpecialType] ?? key;
}

export type FittingComponentType =
  | FittingPeakType
  | "polynomial_background"
  | FittingXpsBgType
  | FittingXpsSpecialType
  | string;


export const PEAK_TYPE_LABELS: Record<FittingPeakType, string> = {
  gaussian: "Gaussian",
  lorentzian: "Lorentzian",
  pseudo_voigt: "Pseudo-Voigt",
  gl: "Gaussian–Lorentzian (GL)",
  voigt: "Voigt",
  ds: "Doniach–Šunjić (DS)",
  gds: "Gaussian-convoluted DS (GDS)",
  la: "Asymmetric Lorentzian (LA)",
  lf: "Finite Lorentzian (LF)",
  a_gl: "Asymmetric GL A(a,n,m)",
  apv: "Asymmetric GL (APV)",
  asymmetric_voigt: "Asymmetric Voigt",
};

export const XPS_BG_TYPE_LABELS: Record<FittingXpsBgType, string> = {
  shirley_bg: "Shirley background (active)",
  tougaard_bg: "Tougaard background (active)",
  slope_bg: "Slope background (active)",
};

export const XPS_SPECIAL_TYPE_LABELS: Record<FittingXpsSpecialType, string> = {
  fermi_edge: "Fermi edge (valence)",
};

export const XPS_REGION_PRESETS = ["O1s", "C1s", "N1s", "S2p", "Ir4f", "Au4f", "Ag3d", "Pt4f", "VB"] as const;

/** Fitting step region sentinel: apply to every region whose name contains valence, fermi, or vb. */
export const ALL_VALENCE_BANDS_REGION = "all valence bands";

export function isValenceBandRegionName(name: string | null | undefined): boolean {
  const s = String(name ?? "").trim().toLowerCase();
  if (!s) return false;
  return s.includes("valence") || s.includes("fermi") || s.includes("vb");
}

/**
 * Compact label for region subset tiles / status line.
 * Core level → region name; all valence bands → ``vb-all``; a VB region → ``vb-{token}``.
 */
export function shortXpsRegionLabel(region: string | null | undefined): string {
  const t = String(region ?? "").trim();
  if (!t) return "";
  if (t.toLowerCase() === ALL_VALENCE_BANDS_REGION) return "vb-all";
  if (!isValenceBandRegionName(t)) return t;
  const vbPrefixed = t.match(/^vb[-_](.+)$/i);
  if (vbPrefixed) return `vb-${vbPrefixed[1].trim()}`;
  if (/^vb$/i.test(t)) return "vb";
  const cleaned = t
    .replace(/valence\s*bands?/gi, "")
    .replace(/valencebands?/gi, "")
    .replace(/fermi(?:\s*edge)?/gi, "")
    .replace(/\bvb\b/gi, "")
    .replace(/^[-_\s]+|[-_\s]+$/g, "")
    .trim();
  return cleaned ? `vb-${cleaned}` : "vb";
}

/** Join short region labels for a multi-pick subset name (e.g. ``C1s+vb-all``). */
export function regionSubsetDisplayName(picks: Iterable<string>): string {
  const parts: string[] = [];
  const seen = new Set<string>();
  for (const p of picks) {
    const short = shortXpsRegionLabel(p);
    if (!short || seen.has(short)) continue;
    seen.add(short);
    parts.push(short);
  }
  return parts.join("+") || "region";
}

/** Whether a spectrum region matches any region-picker selection (incl. all valence bands). */
export function spectrumRegionMatchesPicks(spectrumRegion: string | null | undefined, picks: Iterable<string>): boolean {
  const region = String(spectrumRegion ?? "").trim();
  if (!region) return false;
  for (const p of picks) {
    const wanted = String(p ?? "").trim();
    if (!wanted) continue;
    if (wanted.toLowerCase() === ALL_VALENCE_BANDS_REGION) {
      if (isValenceBandRegionName(region)) return true;
      continue;
    }
    if (wanted.toLowerCase() === region.toLowerCase()) return true;
  }
  return false;
}

/** Match fitting step ``xps_region`` against a spectrum region label (same rules as backend). */
export function fittingRegionMatches(wanted: string | null | undefined, spectrumRegion: string | null | undefined): boolean {
  const w = String(wanted ?? "").trim();
  const s = String(spectrumRegion ?? "").trim();
  if (!w) return true;
  if (!s) return true;
  if (w.toLowerCase() === ALL_VALENCE_BANDS_REGION) return isValenceBandRegionName(s);
  return w.toLowerCase() === s.toLowerCase();
}

export type FittingParamLink = {
  source_component_id: string;
  source_key: string;
  target_component_id: string;
  target_key: string;
  mode: "equal" | "scale" | "offset";
  scale?: number;
  offset?: number;
};

export function isPeakComponentType(ct: string): ct is FittingPeakType {
  return (PEAK_COMPONENT_TYPES as readonly string[]).includes(ct.trim().toLowerCase());
}

export function isXpsBgComponentType(ct: string): ct is FittingXpsBgType {
  const t = ct.trim().toLowerCase();
  return (XPS_BG_COMPONENT_TYPES as readonly string[]).includes(t) || t.endsWith("_bg");
}

export function isXpsSpecialComponentType(ct: string): ct is FittingXpsSpecialType {
  return (XPS_SPECIAL_COMPONENT_TYPES as readonly string[]).includes(ct.trim().toLowerCase());
}

export function isXpsOnlyComponentType(ct: string): boolean {
  return isXpsBgComponentType(ct) || isXpsSpecialComponentType(ct);
}

export function parseFittingComponentType(raw: string | null | undefined): FittingComponentType {
  const ct = String(raw ?? "gaussian").trim().toLowerCase();
  if (ct === "polynomial_background") return "polynomial_background";
  if (isXpsSpecialComponentType(ct)) return ct;
  if (isXpsBgComponentType(ct)) return ct;
  if (isPeakComponentType(ct)) return ct;
  return "gaussian";
}

export type FittingParamRow = {
  key: string;
  label: string;
  p0: number;
  lower: number | null;
  upper: number | null;
  /** When false, parameter is held fixed (XPS/lmfit). Default true. */
  vary?: boolean;
  /**
   * When true (peak / Fermi-edge amplitude), initial guess is auto-estimated at fit time
   * (p0 stored as 0 sentinel).
   */
  auto?: boolean;
};

/** Amplitude params that support per-component Auto initial guess. */
export function isAutoAmplitudeParam(componentType: string, key: string): boolean {
  const ct = String(componentType ?? "").trim().toLowerCase();
  const k = String(key ?? "").trim().toLowerCase();
  if (ct === "fermi_edge" && (k === "amplitude" || k === "const")) return true;
  if (isPeakComponentType(ct) && k === "amp") return true;
  return false;
}

/** Peak-only amp rows (excludes fermi / backgrounds) for area-ratio counting. */
export function isPeakAmplitudeParam(componentType: string, key: string): boolean {
  return isPeakComponentType(componentType) && String(key ?? "").trim().toLowerCase() === "amp";
}

export function countPeakComponents(fp: FittingEditorParams): number {
  return fp.components.filter((c) => isPeakComponentType(c.component_type)).length;
}

/**
 * Parse ``1:0.6:0.3`` style area ratios. Empty string → ok with empty list.
 * Invalid tokens → error (flatten still passes the raw string through).
 */
export function parseInitialAreaRatios(
  raw: string | null | undefined
): { ok: true; ratios: number[] } | { ok: false; error: string; ratios: number[] } {
  const s = String(raw ?? "").trim();
  if (!s) return { ok: true, ratios: [] };
  const parts = s.split(":");
  const ratios: number[] = [];
  for (const part of parts) {
    const t = part.trim();
    if (!t) return { ok: false, error: "Empty ratio segment", ratios: [] };
    const n = Number(t);
    if (!Number.isFinite(n) || n <= 0) {
      return { ok: false, error: `Invalid ratio value: ${t}`, ratios: [] };
    }
    ratios.push(n);
  }
  return { ok: true, ratios };
}

/** Turn Auto on/off for every peak amp and Fermi amplitude/const row. */
export function setBandAmplitudeAutos(fp: FittingEditorParams, on: boolean): FittingEditorParams {
  const components = fp.components.map((c) => ({
    ...c,
    rows: c.rows.map((row) => {
      if (!isAutoAmplitudeParam(c.component_type, row.key)) return row;
      if (on) return { ...row, auto: true, p0: 0 };
      return { ...row, auto: false, p0: row.p0 > 0 ? row.p0 : 1 };
    }),
  }));
  return { ...fp, components, amp_auto_bands: on };
}

/** True when every auto-capable amp row has Auto enabled (empty → false). */
export function allBandAmplitudeAutosOn(fp: FittingEditorParams): boolean {
  let n = 0;
  for (const c of fp.components) {
    for (const row of c.rows) {
      if (!isAutoAmplitudeParam(c.component_type, row.key)) continue;
      n++;
      if (!row.auto) return false;
    }
  }
  return n > 0;
}

/** Keep ``amp_auto_bands`` aligned with individual Auto checkboxes. */
export function syncAmpAutoBandsFlag(fp: FittingEditorParams): FittingEditorParams {
  return { ...fp, amp_auto_bands: allBandAmplitudeAutosOn(fp) };
}

export type FittingComponentEditor = {
  component_id: string;
  component_type: FittingComponentType;
  /** Polynomial degree 0..MAX_POLY_DEGREE; ignored for peak shapes. */
  degree: number;
  rows: FittingParamRow[];
};

export type FittingEditorParams = {
  /** Always "fit"; residual mode removed — residuals are plot/export only. */
  output_mode: "fit";
  /** Plot overlay only (ignored by backend transform). */
  fill_opacity: number;
  /**
   * Legacy global flag (kept for older pipelines). Prefer per-row `auto` on amplitude.
   * "auto" still forces all peak amps on the backend.
   */
  initial_guess_mode: "default" | "auto";
  components: FittingComponentEditor[];
  /** XPS core-level / region label for this fitting step (naming + metadata). */
  xps_region?: string;
  /** XPS/lmfit parameter links (equal, scale, or offset). */
  param_links?: FittingParamLink[];
  /** Provenance: first applied XPS fitting recipe id (backward compat). */
  recipe_id?: string;
  /** All applied XPS fitting recipe ids in order (multi-recipe). */
  recipe_ids?: string[];
  /**
   * Non-background component ids contributed by each applied recipe.
   * Used to remove a stacked recipe and its peaks without touching the shared baseline.
   */
  recipe_components?: Record<string, string[]>;
  /** Pass energy used when applying the recipe (eV). */
  recipe_pass_energy?: number;
  /** Optional internal fit window lower bound (inclusive). Empty/undefined = full spectrum. */
  fit_min_x?: number | null;
  /** Optional internal fit window upper bound (inclusive). Empty/undefined = full spectrum. */
  fit_max_x?: number | null;
  /** Master Auto-guess for band/peak amplitudes (and Fermi amp/const). */
  amp_auto_bands?: boolean;
  /**
   * Optional Area1:Area2:... ratios for peak components in list order.
   * Used only when band amplitude Auto is on (initial guess; not locked).
   */
  initial_area_ratios?: string;
  /**
   * Cumulative rigid shift (eV) applied to all peak ``pos`` seeds/bounds vs the
   * last recipe apply (0 = recipe BE as applied).
   */
  peak_shift_eV?: number;
};

/** Step used by Peak shift ▲/▼ controls. */
export const PEAK_SHIFT_STEP_EV = 0.2;

/**
 * Set cumulative peak BE shift. Adjusts every peak ``pos`` p0 and bounds by
 * ``nextShift - previous peak_shift_eV`` (relative links keep their offsets).
 */
export function applyPeakShiftEv(fp: FittingEditorParams, nextShiftRaw: number): FittingEditorParams {
  const prev =
    typeof fp.peak_shift_eV === "number" && Number.isFinite(fp.peak_shift_eV) ? fp.peak_shift_eV : 0;
  const next = Number.isFinite(nextShiftRaw) ? Math.round(Number(nextShiftRaw) * 1000) / 1000 : 0;
  const d = next - prev;
  if (Math.abs(d) < 1e-12) {
    return fp.peak_shift_eV === next ? fp : { ...fp, peak_shift_eV: next };
  }
  const components = fp.components.map((c) => {
    if (!isPeakComponentType(c.component_type)) return c;
    return {
      ...c,
      rows: c.rows.map((row) => {
        if (String(row.key).trim().toLowerCase() !== "pos") return row;
        const lower =
          row.lower != null && Number.isFinite(row.lower) ? Number(row.lower) + d : row.lower;
        const upper =
          row.upper != null && Number.isFinite(row.upper) ? Number(row.upper) + d : row.upper;
        return {
          ...row,
          p0: Number(row.p0) + d,
          lower,
          upper,
        };
      }),
    };
  });
  return { ...fp, components, peak_shift_eV: next };
}

function optionalFiniteNumber(v: unknown): number | null | undefined {
  if (v === null) return null;
  if (v === undefined || v === "") return undefined;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

function normalizeRecipeIds(raw: unknown, fallbackId?: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const push = (s: string) => {
    const t = s.trim();
    if (!t || seen.has(t)) return;
    seen.add(t);
    out.push(t);
  };
  if (Array.isArray(raw)) {
    for (const x of raw) push(String(x ?? ""));
  }
  if (fallbackId) push(fallbackId);
  return out;
}

function normalizeRecipeComponents(raw: unknown): Record<string, string[]> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, string[]> = {};
  for (const [rid, ids] of Object.entries(raw as Record<string, unknown>)) {
    const key = String(rid || "").trim();
    if (!key || !Array.isArray(ids)) continue;
    const cleaned = ids.map((x) => String(x ?? "").trim()).filter(Boolean);
    if (cleaned.length) out[key] = cleaned;
  }
  return out;
}

export function polynomialParamKeys(degree: number): string[] {
  const d = Math.max(0, Math.min(MAX_POLY_DEGREE, Math.floor(degree)));
  const keys: string[] = [];
  for (let k = d; k >= 0; k--) keys.push(`c${k}`);
  return keys;
}

export const INFINITE_AREA_PEAK_TYPES = new Set<FittingPeakType>(["ds", "gds"]);

/** Vibrational peak keys only — XPS peak/bg shapes require `/fitting/models` catalog. */
export const FALLBACK_PEAK_KEYS: Record<FittingPeakType, string[]> = {
  gaussian: ["pos", "amp", "fwhm"],
  lorentzian: ["pos", "amp", "fwhm"],
  pseudo_voigt: ["pos", "amp", "fwhm", "eta"],
  gl: ["pos", "amp", "fwhm", "m"],
  voigt: ["pos", "amp", "fwhm_g", "fwhm_l"],
  ds: ["pos", "amp", "gamma", "alpha"],
  gds: ["pos", "amp", "gamma", "alpha", "sigma"],
  la: ["pos", "amp", "fwhm", "alpha", "beta", "fwhm_g"],
  lf: ["pos", "amp", "fwhm", "alpha", "beta", "w", "fwhm_g"],
  a_gl: ["pos", "amp", "fwhm", "m", "a", "n", "m_asym"],
  apv: ["pos", "amp", "fwhm_l", "fwhm_r", "eta_l", "eta_r"],
  asymmetric_voigt: ["pos", "amp", "fwhm_g_l", "fwhm_l_l", "fwhm_g_r", "fwhm_l_r"],
};

const FALLBACK_PEAK_P0: Record<string, number> = {
  pos: 1000,
  amp: 1,
  fwhm: 10,
  fwhm_g: 0,
  fwhm_l: 10,
  fwhm_r: 10,
  fwhm_g_l: 8,
  fwhm_l_l: 6,
  fwhm_g_r: 8,
  fwhm_l_r: 6,
  eta: 0.5,
  eta_l: 0.5,
  eta_r: 0.5,
  m: 30,
  a: 0.4,
  n: 0.55,
  m_asym: 10,
  gamma: 5,
  sigma: 3,
  w: 20,
};

/** Per-type overrides when catalog defaults are unavailable (alpha means different things). */
const FALLBACK_PEAK_P0_BY_TYPE: Partial<Record<FittingPeakType, Record<string, number>>> = {
  ds: { alpha: 0.1 },
  gds: { alpha: 0.1 },
  la: { alpha: 1.5, beta: 1.0, fwhm_g: 0 },
  lf: { alpha: 1.5, beta: 1.0, fwhm_g: 0, w: 20 },
  voigt: { fwhm_g: 10, fwhm_l: 10 },
};

export function paramKeysForComponent(
  componentType: string,
  degree: number,
  catalog: FittingComponentSpecPublic[] | undefined
): { keys: string[]; labels: Map<string, string> } {
  const ct = componentType.trim().toLowerCase();
  if (isPeakComponentType(ct)) {
    const spec = catalog?.find((c) => c.component_type === ct);
    const keys = spec?.params?.map((p) => p.key) ?? FALLBACK_PEAK_KEYS[ct];
    const labels = new Map<string, string>();
    for (const p of spec?.params ?? []) labels.set(p.key, p.label);
    for (const k of keys) if (!labels.has(k)) labels.set(k, k);
    return { keys, labels };
  }
  if (isXpsOnlyComponentType(ct)) {
    const spec = catalog?.find((c) => c.component_type === ct);
    const keys = spec?.params?.map((p) => p.key) ?? [];
    const labels = new Map<string, string>();
    for (const p of spec?.params ?? []) labels.set(p.key, p.label);
    for (const k of keys) if (!labels.has(k)) labels.set(k, k);
    return { keys, labels };
  }
  if (ct === "polynomial_background") {
    const d = Math.max(0, Math.min(MAX_POLY_DEGREE, Math.floor(degree)));
    const keys = polynomialParamKeys(d);
    const labels = new Map<string, string>();
    for (const k of keys) labels.set(k, k.replace(/^c/, "Coeff "));
    return { keys, labels };
  }
  return { keys: [], labels: new Map() };
}

export function defaultRowsForComponent(
  componentType: FittingComponentType,
  degree: number,
  catalog: FittingComponentSpecPublic[] | undefined
): FittingParamRow[] {
  const { keys, labels } = paramKeysForComponent(componentType, degree, catalog);
  const byKey = new Map<string, FittingParamSpecPublic>();
  if (isPeakComponentType(componentType) || isXpsOnlyComponentType(componentType)) {
    const spec = catalog?.find((c) => c.component_type === componentType);
    if (spec) {
      for (const p of spec.params) byKey.set(p.key, p);
    }
  }
  if (componentType === "polynomial_background" && catalog) {
    const polySpec = catalog.find(
      (c) => c.component_type === "polynomial_background" && c.params.length === keys.length
    );
    if (polySpec) {
      for (const p of polySpec.params) byKey.set(p.key, p);
    }
  }

  return keys.map((k) => {
    const ps = byKey.get(k);
    const def = ps?.default;
    const lo = ps?.bounds_default?.lower ?? null;
    const hi = ps?.bounds_default?.upper ?? null;
    const ui = (ps?.ui ?? {}) as Record<string, unknown>;
    let p0 = 0;
    if (typeof def === "number" && Number.isFinite(def)) {
      p0 = def;
    } else if (isPeakComponentType(componentType)) {
      const typed = FALLBACK_PEAK_P0_BY_TYPE[componentType]?.[k];
      p0 = typeof typed === "number" ? typed : (FALLBACK_PEAK_P0[k] ?? 0);
    } else if (isXpsOnlyComponentType(componentType)) {
      // XPS bg / special p0/keys come from `/fitting/models` only.
      p0 = 0;
    }
    const varyDefault = ui.vary_default === false ? false : true;
    const autoDefault = ui.auto_default === true || isAutoAmplitudeParam(componentType, k);
    return {
      key: k,
      label: labels.get(k) ?? k,
      p0: autoDefault ? 0 : p0,
      lower: ui.bounds_editable === false ? null : (lo ?? null),
      upper: ui.bounds_editable === false ? null : (hi ?? null),
      vary: varyDefault,
      ...(autoDefault ? { auto: true } : {}),
    };
  });
}

function looksLikeUuid(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(s.trim());
}

/** For editor display: drop legacy random ids so the user sees an empty peak name until save. */
function stripLegacyFittingComponentId(id: string): string {
  const t = String(id ?? "").trim();
  return looksLikeUuid(t) ? "" : t;
}

function sanitizePeakFragment(s: string): string {
  const t = s.trim().replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  return t || "";
}

/**
 * Assigns stable peak ids for the pipeline: empty names become p1, p2, …;
 * non-empty names are sanitized; collisions get numeric suffixes (_2, _3, …).
 */
export function assignPeakNames(components: FittingComponentEditor[]): FittingComponentEditor[] {
  const used = new Set<string>();
  return components.map((comp) => {
    const raw = String(comp.component_id ?? "").trim();
    if (!raw || looksLikeUuid(raw)) {
      return { ...comp, component_id: uniqueComponentIdAgainst("p", used, { preferAutoP: true }) };
    }
    return { ...comp, component_id: uniqueComponentIdAgainst(raw, used) };
  });
}

/**
 * Rename a component while retaining references that use its id. Parameter links
 * and recipe ownership are both id-based, rather than position-based.
 */
export function renameFittingComponent(
  fp: FittingEditorParams,
  componentIndex: number,
  componentId: string
): FittingEditorParams {
  const current = fp.components[componentIndex];
  if (!current) return fp;
  const previousId = String(current.component_id ?? "");
  if (previousId === componentId) return fp;

  const components = fp.components.slice();
  components[componentIndex] = { ...current, component_id: componentId };
  const remap = (id: string) => (id === previousId ? componentId : id);
  const param_links = (fp.param_links ?? []).map((link) => ({
    ...link,
    source_component_id: remap(link.source_component_id),
    target_component_id: remap(link.target_component_id),
  }));
  const recipe_components = Object.fromEntries(
    Object.entries(fp.recipe_components ?? {}).map(([recipeId, ids]) => [
      recipeId,
      ids.map(remap),
    ])
  );
  return { ...fp, components, param_links, recipe_components };
}

const TRAILING_NUM_RE = /^(.*?)([-_ ]?)(\d+)$/;

/**
 * Return a component id unique against ``used`` (case-insensitive).
 * Increments a trailing number when present (Peak_1 → Peak_2); else ``base_2``.
 */
export function uniqueComponentIdAgainst(
  label: string,
  used: Set<string>,
  opts?: { preferAutoP?: boolean }
): string {
  const has = (s: string) => used.has(s.toLowerCase());
  const take = (s: string) => {
    used.add(s.toLowerCase());
    return s;
  };

  if (opts?.preferAutoP) {
    let k = 1;
    while (has(`p${k}`)) k++;
    return take(`p${k}`);
  }

  const base = sanitizePeakFragment(label) || "p";
  if (!has(base)) return take(base);

  const m = TRAILING_NUM_RE.exec(base);
  if (m) {
    const prefix = m[1] ?? "";
    const sep = m[2] || "_";
    let n = Number(m[3]) + 1;
    while (true) {
      const cand = prefix ? `${prefix}${sep}${n}` : `p${n}`;
      if (!has(cand)) return take(cand);
      n++;
    }
  }

  let i = 2;
  while (true) {
    const id = `${base}_${i}`;
    if (!has(id)) return take(id);
    i++;
  }
}

export function defaultFittingEditorParams(catalog: FittingComponentSpecPublic[] | undefined): FittingEditorParams {
  return {
    output_mode: "fit",
    fill_opacity: 0.15,
    initial_guess_mode: "default",
    components: [
      {
        component_id: "",
        component_type: "gaussian",
        degree: 0,
        rows: defaultRowsForComponent("gaussian", 0, catalog),
      },
    ],
    xps_region: "",
    param_links: [],
    recipe_id: "",
    recipe_ids: [],
    recipe_components: {},
    recipe_pass_energy: undefined,
    fit_min_x: null,
    fit_max_x: null,
    amp_auto_bands: false,
    initial_area_ratios: "",
    peak_shift_eV: 0,
  };
}

function isStructuredFittingParams(p: unknown): p is FittingEditorParams {
  if (!p || typeof p !== "object") return false;
  const o = p as Record<string, unknown>;
  if (!Array.isArray(o.components) || o.components.length === 0) return false;
  const c0 = o.components[0] as Record<string, unknown>;
  return Array.isArray(c0?.rows);
}

function normalizeParamLinks(raw: unknown): FittingParamLink[] {
  if (!Array.isArray(raw)) return [];
  const out: FittingParamLink[] = [];
  for (const row of raw) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const modeRaw = String(r.mode ?? "equal").trim().toLowerCase();
    const mode: FittingParamLink["mode"] =
      modeRaw === "scale" ? "scale" : modeRaw === "offset" ? "offset" : "equal";
    const link: FittingParamLink = {
      source_component_id: String(r.source_component_id ?? ""),
      source_key: String(r.source_key ?? ""),
      target_component_id: String(r.target_component_id ?? ""),
      target_key: String(r.target_key ?? ""),
      mode,
    };
    if (mode === "scale" && typeof r.scale === "number" && Number.isFinite(r.scale)) {
      link.scale = r.scale;
    }
    if (mode === "offset" && typeof r.offset === "number" && Number.isFinite(r.offset)) {
      link.offset = r.offset;
    }
    if (link.source_component_id && link.source_key && link.target_component_id && link.target_key) {
      out.push(link);
    }
  }
  return out;
}

/** Pipeline/backend shape: flattened bounds + component list without rows. */
export function flattenFittingForPipeline(fp: FittingEditorParams): Record<string, unknown> {
  const named = assignPeakNames(fp.components);
  const components: { component_id: string; component_type: string; degree?: number }[] = [];
  const p0: number[] = [];
  const bounds_lower: (number | null)[] = [];
  const bounds_upper: (number | null)[] = [];
  const vary: boolean[] = [];
  for (const c of named) {
    components.push({
      component_id: c.component_id,
      component_type: c.component_type,
      ...(c.component_type === "polynomial_background" ? { degree: c.degree } : {}),
    });
    for (const r of c.rows) {
      // Auto amplitude: send ≤0 sentinel so the engine estimates height at fit time.
      p0.push(r.auto ? 0 : r.p0);
      bounds_lower.push(r.lower);
      bounds_upper.push(r.upper);
      vary.push(r.vary !== false);
    }
  }
  const region = String(fp.xps_region ?? "").trim();
  const validParamKeys = new Set(
    named.flatMap((component) => component.rows.map((row) => linkKey(component.component_id, row.key)))
  );
  // A legacy draft can retain a link after deleting a peak or changing its model.
  // Do not send those dangling links to the fitter.
  const links = normalizeParamLinks(fp.param_links).filter(
    (link) =>
      validParamKeys.has(linkKey(link.source_component_id, link.source_key)) &&
      validParamKeys.has(linkKey(link.target_component_id, link.target_key))
  );
  const out: Record<string, unknown> = {
    output_mode: fp.output_mode,
    fill_opacity: fp.fill_opacity,
    // Per-peak Auto uses amp ≤0 sentinels; keep legacy field as default.
    initial_guess_mode: "default",
    components,
    p0,
    bounds_lower,
    bounds_upper,
    vary,
  };
  if (region) out.xps_region = region;
  if (links.length) out.param_links = links;
  const recipeIds = normalizeRecipeIds(fp.recipe_ids, String(fp.recipe_id ?? "").trim() || undefined);
  if (recipeIds.length) {
    out.recipe_id = recipeIds[0];
    out.recipe_ids = recipeIds;
  }
  const recipeComponents = normalizeRecipeComponents(fp.recipe_components);
  if (Object.keys(recipeComponents).length) out.recipe_components = recipeComponents;
  if (typeof fp.recipe_pass_energy === "number" && Number.isFinite(fp.recipe_pass_energy)) {
    out.recipe_pass_energy = fp.recipe_pass_energy;
  }
  const fitMin = optionalFiniteNumber(fp.fit_min_x);
  const fitMax = optionalFiniteNumber(fp.fit_max_x);
  if (fitMin != null) out.fit_min_x = fitMin;
  if (fitMax != null) out.fit_max_x = fitMax;
  if (fp.amp_auto_bands) out.amp_auto_bands = true;
  const ratios = String(fp.initial_area_ratios ?? "").trim();
  if (ratios && fp.amp_auto_bands) out.initial_area_ratios = ratios;
  const peakShift =
    typeof fp.peak_shift_eV === "number" && Number.isFinite(fp.peak_shift_eV) ? fp.peak_shift_eV : 0;
  if (peakShift !== 0) out.peak_shift_eV = peakShift;
  return out;
}

export function migrateFittingParamsToEditor(
  raw: Record<string, unknown> | null | undefined,
  catalog: FittingComponentSpecPublic[] | undefined
): FittingEditorParams {
  if (isStructuredFittingParams(raw)) {
    const r = raw as FittingEditorParams;
    const legacyGlobalAuto = r.initial_guess_mode === "auto";
    const recipe_id = typeof r.recipe_id === "string" ? r.recipe_id : "";
    const components = r.components.map((c) => ({
      ...c,
      component_type: parseFittingComponentType(c.component_type),
      component_id: stripLegacyFittingComponentId(c.component_id),
      rows: c.rows.map((row) => {
        const base = { ...row, vary: row.key === "temperature_K" ? false : row.vary !== false };
        const ct = parseFittingComponentType(c.component_type);
        if (
          isAutoAmplitudeParam(ct, row.key) &&
          (row.auto ||
            legacyGlobalAuto ||
            !(typeof row.p0 === "number") ||
            !Number.isFinite(row.p0) ||
            row.p0 <= 0)
        ) {
          return { ...base, auto: true, p0: 0 };
        }
        return base;
      }),
    }));
    const next: FittingEditorParams = {
      ...r,
      initial_guess_mode: "default",
      xps_region: typeof r.xps_region === "string" ? r.xps_region : "",
      param_links: normalizeParamLinks(r.param_links),
      recipe_id,
      recipe_ids: normalizeRecipeIds(r.recipe_ids, recipe_id || undefined),
      recipe_components: normalizeRecipeComponents(r.recipe_components),
      recipe_pass_energy:
        typeof r.recipe_pass_energy === "number" && Number.isFinite(r.recipe_pass_energy)
          ? r.recipe_pass_energy
          : undefined,
      fit_min_x: optionalFiniteNumber(r.fit_min_x) ?? null,
      fit_max_x: optionalFiniteNumber(r.fit_max_x) ?? null,
      initial_area_ratios: typeof r.initial_area_ratios === "string" ? r.initial_area_ratios : "",
      peak_shift_eV:
        typeof r.peak_shift_eV === "number" && Number.isFinite(r.peak_shift_eV) ? r.peak_shift_eV : 0,
      components,
      amp_auto_bands: Boolean(r.amp_auto_bands),
    };
    return syncAmpAutoBandsFlag({
      ...next,
      amp_auto_bands: r.amp_auto_bands === true || allBandAmplitudeAutosOn(next),
    });
  }
  const p = raw ?? {};
  const output_mode = "fit" as const;
  const fill_opacity = typeof p.fill_opacity === "number" && Number.isFinite(p.fill_opacity) ? p.fill_opacity : 0.15;
  const legacyGlobalAuto = p.initial_guess_mode === "auto";
  const initial_guess_mode = "default" as const;
  const xps_region = typeof p.xps_region === "string" ? p.xps_region : "";
  const param_links = normalizeParamLinks(p.param_links);
  const recipe_id = typeof p.recipe_id === "string" ? p.recipe_id : "";
  const recipe_ids = normalizeRecipeIds(p.recipe_ids, recipe_id || undefined);
  const recipe_components = normalizeRecipeComponents(p.recipe_components);
  const recipe_pass_energy =
    typeof p.recipe_pass_energy === "number" && Number.isFinite(p.recipe_pass_energy)
      ? Number(p.recipe_pass_energy)
      : undefined;
  const fit_min_x = optionalFiniteNumber(p.fit_min_x) ?? null;
  const fit_max_x = optionalFiniteNumber(p.fit_max_x) ?? null;
  const amp_auto_bands_raw = p.amp_auto_bands === true;
  const initial_area_ratios = typeof p.initial_area_ratios === "string" ? p.initial_area_ratios : "";
  const peak_shift_eV =
    typeof p.peak_shift_eV === "number" && Number.isFinite(p.peak_shift_eV) ? Number(p.peak_shift_eV) : 0;
  const comps = p.components;
  const p0 = p.p0;
  const lo = p.bounds_lower;
  const hi = p.bounds_upper;
  const varyRaw = p.vary;
  if (!Array.isArray(comps) || !Array.isArray(p0) || !Array.isArray(lo) || !Array.isArray(hi)) {
    return defaultFittingEditorParams(catalog);
  }
  let off = 0;
  const out: FittingComponentEditor[] = [];
  for (const row of comps) {
    if (!row || typeof row !== "object") continue;
    const cr = row as Record<string, unknown>;
    const component_id = stripLegacyFittingComponentId(String(cr.component_id ?? ""));
    const component_type = parseFittingComponentType(String(cr.component_type || "gaussian"));
    const degree =
      typeof cr.degree === "number" && Number.isFinite(cr.degree)
        ? Math.max(0, Math.min(MAX_POLY_DEGREE, Math.floor(cr.degree)))
        : 2;
    const { keys, labels } = paramKeysForComponent(component_type, degree, catalog);
    const n = keys.length;
    const remaining = (p0 as unknown[]).length - off;
    // Legacy fermi_edge was 4 params (no const floor); catalog now expects 5.
    const padConst =
      component_type === "fermi_edge" &&
      n >= 1 &&
      keys[n - 1] === "const" &&
      remaining === n - 1;
    const take = padConst ? n - 1 : n;
    if (remaining < take) {
      return defaultFittingEditorParams(catalog);
    }
    const defaults = defaultRowsForComponent(component_type, degree, catalog);
    const defByKey = new Map(defaults.map((r) => [r.key, r]));
    const rows: FittingParamRow[] = [];
    for (let i = 0; i < n; i++) {
      const k = keys[i]!;
      const missing = i >= take;
      const pv = missing ? undefined : p0[off + i];
      const lv = missing ? defByKey.get(k)?.lower : lo[off + i];
      const uv = missing ? defByKey.get(k)?.upper : hi[off + i];
      const vv = missing
        ? defByKey.get(k)?.vary !== false
        : Array.isArray(varyRaw)
          ? varyRaw[off + i]
          : true;
      const p0Val =
        typeof pv === "number" && Number.isFinite(pv)
          ? pv
          : (defByKey.get(k)?.p0 ?? 0);
      const wantAuto =
        isAutoAmplitudeParam(component_type, k) &&
        (legacyGlobalAuto ||
          missing ||
          !(typeof pv === "number") ||
          !Number.isFinite(pv) ||
          pv <= 0);
      rows.push({
        key: k,
        label: labels.get(k) ?? k,
        p0: wantAuto ? 0 : p0Val,
        lower: lv === null || lv === undefined ? null : (typeof lv === "number" && Number.isFinite(lv) ? lv : null),
        upper: uv === null || uv === undefined ? null : (typeof uv === "number" && Number.isFinite(uv) ? uv : null),
        vary: k === "temperature_K" ? false : vv !== false,
        ...(wantAuto ? { auto: true } : {}),
      });
    }
    off += take;
    out.push({ component_id, component_type, degree, rows });
  }
  if (off !== (p0 as unknown[]).length) {
    return defaultFittingEditorParams(catalog);
  }
  const baseComps = out.length ? out : defaultFittingEditorParams(catalog).components;
  const migrated: FittingEditorParams = {
    output_mode,
    fill_opacity,
    initial_guess_mode,
    components: assignPeakNames(baseComps),
    xps_region,
    param_links,
    recipe_id: recipe_ids[0] ?? recipe_id,
    recipe_ids,
    recipe_components,
    recipe_pass_energy,
    fit_min_x,
    fit_max_x,
    amp_auto_bands: amp_auto_bands_raw,
    initial_area_ratios,
    peak_shift_eV,
  };
  return syncAmpAutoBandsFlag({
    ...migrated,
    amp_auto_bands: amp_auto_bands_raw || allBandAmplitudeAutosOn(migrated),
  });
}

export function linkKey(componentId: string, paramKey: string): string {
  return `${componentId}::${paramKey}`;
}

export function findParamLink(
  links: FittingParamLink[] | undefined,
  componentId: string,
  paramKey: string
): FittingParamLink | undefined {
  return (links ?? []).find((l) => l.source_component_id === componentId && l.source_key === paramKey);
}

export function upsertParamLink(
  links: FittingParamLink[] | undefined,
  next: FittingParamLink | null,
  componentId: string,
  paramKey: string
): FittingParamLink[] {
  const filtered = (links ?? []).filter((l) => !(l.source_component_id === componentId && l.source_key === paramKey));
  if (!next) return filtered;
  return [...filtered, next];
}
