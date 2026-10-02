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
   * When true (Fermi-edge amplitude), initial guess is auto-estimated at fit time
   * (p0 stored as 0 sentinel).
   */
  auto?: boolean;
};

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
   * default: use table p0 for all parameters.
   * auto: backend sets peak initial amplitude to spectrum intensity at the initial center (pos).
   */
  initial_guess_mode: "default" | "auto";
  components: FittingComponentEditor[];
  /** XPS core-level / region label for this fitting step (naming + metadata). */
  xps_region?: string;
  /** XPS/lmfit parameter links (equal, scale, or offset). */
  param_links?: FittingParamLink[];
  /** Provenance: applied XPS fitting recipe id. */
  recipe_id?: string;
  /** Pass energy used when applying the recipe (eV). */
  recipe_pass_energy?: number;
};

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
    const autoDefault = ui.auto_default === true;
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
  const has = (s: string) => used.has(s.toLowerCase());
  const take = (s: string) => void used.add(s.toLowerCase());

  const nextAuto = (): string => {
    let k = 1;
    while (has(`p${k}`)) k++;
    const id = `p${k}`;
    take(id);
    return id;
  };

  const uniqueFromBase = (raw: string): string => {
    const base = sanitizePeakFragment(raw) || "p";
    if (!has(base)) {
      take(base);
      return base;
    }
    let i = 2;
    let id = `${base}_${i}`;
    while (has(id)) {
      i++;
      id = `${base}_${i}`;
    }
    take(id);
    return id;
  };

  return components.map((comp) => {
    const raw = String(comp.component_id ?? "").trim();
    if (!raw || looksLikeUuid(raw)) {
      return { ...comp, component_id: nextAuto() };
    }
    return { ...comp, component_id: uniqueFromBase(raw) };
  });
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
    recipe_pass_energy: undefined,
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
      // Auto amplitude: send ≤0 sentinel so the XPS engine estimates step height.
      p0.push(r.auto ? 0 : r.p0);
      bounds_lower.push(r.lower);
      bounds_upper.push(r.upper);
      vary.push(r.vary !== false);
    }
  }
  const region = String(fp.xps_region ?? "").trim();
  const links = normalizeParamLinks(fp.param_links);
  const out: Record<string, unknown> = {
    output_mode: fp.output_mode,
    fill_opacity: fp.fill_opacity,
    initial_guess_mode: fp.initial_guess_mode,
    components,
    p0,
    bounds_lower,
    bounds_upper,
    vary,
  };
  if (region) out.xps_region = region;
  if (links.length) out.param_links = links;
  const recipeId = String(fp.recipe_id ?? "").trim();
  if (recipeId) out.recipe_id = recipeId;
  if (typeof fp.recipe_pass_energy === "number" && Number.isFinite(fp.recipe_pass_energy)) {
    out.recipe_pass_energy = fp.recipe_pass_energy;
  }
  return out;
}

export function migrateFittingParamsToEditor(
  raw: Record<string, unknown> | null | undefined,
  catalog: FittingComponentSpecPublic[] | undefined
): FittingEditorParams {
  if (isStructuredFittingParams(raw)) {
    const r = raw as FittingEditorParams;
    return {
      ...r,
      initial_guess_mode: r.initial_guess_mode === "auto" ? "auto" : "default",
      xps_region: typeof r.xps_region === "string" ? r.xps_region : "",
      param_links: normalizeParamLinks(r.param_links),
      recipe_id: typeof r.recipe_id === "string" ? r.recipe_id : "",
      recipe_pass_energy:
        typeof r.recipe_pass_energy === "number" && Number.isFinite(r.recipe_pass_energy)
          ? r.recipe_pass_energy
          : undefined,
      components: r.components.map((c) => ({
        ...c,
        component_type: parseFittingComponentType(c.component_type),
        component_id: stripLegacyFittingComponentId(c.component_id),
        rows: c.rows.map((row) => {
          const base = { ...row, vary: row.key === "temperature_K" ? false : row.vary !== false };
          if (
            parseFittingComponentType(c.component_type) === "fermi_edge" &&
            row.key === "amplitude" &&
            (row.auto || !(typeof row.p0 === "number") || !Number.isFinite(row.p0) || row.p0 <= 0)
          ) {
            return { ...base, auto: true, p0: 0 };
          }
          return base;
        }),
      })),
    };
  }
  const p = raw ?? {};
  const output_mode = "fit" as const;
  const fill_opacity = typeof p.fill_opacity === "number" && Number.isFinite(p.fill_opacity) ? p.fill_opacity : 0.15;
  const initial_guess_mode = p.initial_guess_mode === "auto" ? "auto" : "default";
  const xps_region = typeof p.xps_region === "string" ? p.xps_region : "";
  const param_links = normalizeParamLinks(p.param_links);
  const recipe_id = typeof p.recipe_id === "string" ? p.recipe_id : "";
  const recipe_pass_energy =
    typeof p.recipe_pass_energy === "number" && Number.isFinite(p.recipe_pass_energy)
      ? Number(p.recipe_pass_energy)
      : undefined;
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
    const rows: FittingParamRow[] = [];
    for (let i = 0; i < n; i++) {
      const k = keys[i]!;
      const pv = p0[off + i];
      const lv = lo[off + i];
      const uv = hi[off + i];
      const vv = Array.isArray(varyRaw) ? varyRaw[off + i] : true;
      rows.push({
        key: k,
        label: labels.get(k) ?? k,
        p0: typeof pv === "number" && Number.isFinite(pv) ? pv : 0,
        lower: lv === null || lv === undefined ? null : (typeof lv === "number" && Number.isFinite(lv) ? lv : null),
        upper: uv === null || uv === undefined ? null : (typeof uv === "number" && Number.isFinite(uv) ? uv : null),
        vary: k === "temperature_K" ? false : vv !== false,
        ...(component_type === "fermi_edge" && k === "amplitude" && (!(typeof pv === "number") || !Number.isFinite(pv) || pv <= 0)
          ? { auto: true, p0: 0 }
          : {}),
      });
    }
    off += n;
    out.push({ component_id, component_type, degree, rows });
  }
  if (off !== (p0 as unknown[]).length) {
    return defaultFittingEditorParams(catalog);
  }
  const baseComps = out.length ? out : defaultFittingEditorParams(catalog).components;
  return {
    output_mode,
    fill_opacity,
    initial_guess_mode,
    components: assignPeakNames(baseComps),
    xps_region,
    param_links,
    recipe_id,
    recipe_pass_energy,
  };
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
