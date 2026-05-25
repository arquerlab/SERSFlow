import type { FittingComponentSpecPublic, FittingParamSpecPublic } from "./api";

export const MAX_POLY_DEGREE = 12;

export type FittingParamRow = {
  key: string;
  label: string;
  p0: number;
  lower: number | null;
  upper: number | null;
};

export type FittingComponentEditor = {
  component_id: string;
  component_type: "gaussian" | "polynomial_background";
  /** Polynomial degree 0..MAX_POLY_DEGREE; ignored for gaussian. */
  degree: number;
  rows: FittingParamRow[];
};

export type FittingEditorParams = {
  output_mode: "fit" | "residual";
  /** Plot overlay only (ignored by backend transform). */
  fill_opacity: number;
  /**
   * default: use table p0 for all parameters.
   * auto: backend sets Gaussian initial amplitude to spectrum intensity at the initial center (pos).
   */
  initial_guess_mode: "default" | "auto";
  components: FittingComponentEditor[];
};

export function polynomialParamKeys(degree: number): string[] {
  const d = Math.max(0, Math.min(MAX_POLY_DEGREE, Math.floor(degree)));
  const keys: string[] = [];
  for (let k = d; k >= 0; k--) keys.push(`c${k}`);
  return keys;
}

export function paramKeysForComponent(
  componentType: string,
  degree: number,
  catalog: FittingComponentSpecPublic[] | undefined
): { keys: string[]; labels: Map<string, string> } {
  const ct = componentType.trim().toLowerCase();
  if (ct === "gaussian") {
    const spec = catalog?.find((c) => c.component_type === "gaussian");
    const keys = spec?.params?.map((p) => p.key) ?? ["pos", "amp", "fwhm"];
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
  componentType: "gaussian" | "polynomial_background",
  degree: number,
  catalog: FittingComponentSpecPublic[] | undefined
): FittingParamRow[] {
  const { keys, labels } = paramKeysForComponent(componentType, degree, catalog);
  const spec = catalog?.find(
    (c) =>
      c.component_type === (componentType === "polynomial_background" ? `polynomial_background` : "gaussian")
  );
  const byKey = new Map<string, FittingParamSpecPublic>();
  if (componentType === "gaussian" && spec) {
    for (const p of spec.params) byKey.set(p.key, p);
  }
  // For polynomial, match degree from catalog if present
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
    let p0 = 0;
    if (typeof def === "number" && Number.isFinite(def)) {
      p0 = def;
    } else if (componentType === "gaussian") {
      if (k === "pos") p0 = 1000;
      else if (k === "amp") p0 = 1;
      else if (k === "fwhm") p0 = 10;
    }
    return {
      key: k,
      label: labels.get(k) ?? k,
      p0,
      lower: lo ?? null,
      upper: hi ?? null,
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
  };
}

function isStructuredFittingParams(p: unknown): p is FittingEditorParams {
  if (!p || typeof p !== "object") return false;
  const o = p as Record<string, unknown>;
  if (!Array.isArray(o.components) || o.components.length === 0) return false;
  const c0 = o.components[0] as Record<string, unknown>;
  return Array.isArray(c0?.rows);
}

/** Pipeline/backend shape: flattened bounds + component list without rows. */
export function flattenFittingForPipeline(fp: FittingEditorParams): Record<string, unknown> {
  const named = assignPeakNames(fp.components);
  const components: { component_id: string; component_type: string; degree?: number }[] = [];
  const p0: number[] = [];
  const bounds_lower: (number | null)[] = [];
  const bounds_upper: (number | null)[] = [];
  for (const c of named) {
    components.push({
      component_id: c.component_id,
      component_type: c.component_type,
      ...(c.component_type === "polynomial_background" ? { degree: c.degree } : {}),
    });
    for (const r of c.rows) {
      p0.push(r.p0);
      bounds_lower.push(r.lower);
      bounds_upper.push(r.upper);
    }
  }
  return {
    output_mode: fp.output_mode,
    fill_opacity: fp.fill_opacity,
    initial_guess_mode: fp.initial_guess_mode,
    components,
    p0,
    bounds_lower,
    bounds_upper,
  };
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
      components: r.components.map((c) => ({
        ...c,
        component_id: stripLegacyFittingComponentId(c.component_id),
      })),
    };
  }
  const p = raw ?? {};
  const output_mode = p.output_mode === "residual" ? "residual" : "fit";
  const fill_opacity = typeof p.fill_opacity === "number" && Number.isFinite(p.fill_opacity) ? p.fill_opacity : 0.15;
  const initial_guess_mode = p.initial_guess_mode === "auto" ? "auto" : "default";
  const comps = p.components;
  const p0 = p.p0;
  const lo = p.bounds_lower;
  const hi = p.bounds_upper;
  if (!Array.isArray(comps) || !Array.isArray(p0) || !Array.isArray(lo) || !Array.isArray(hi)) {
    return defaultFittingEditorParams(catalog);
  }
  let off = 0;
  const out: FittingComponentEditor[] = [];
  for (const row of comps) {
    if (!row || typeof row !== "object") continue;
    const cr = row as Record<string, unknown>;
    const component_id = stripLegacyFittingComponentId(String(cr.component_id ?? ""));
    const component_type = (String(cr.component_type || "gaussian") === "polynomial_background"
      ? "polynomial_background"
      : "gaussian") as FittingComponentEditor["component_type"];
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
      rows.push({
        key: k,
        label: labels.get(k) ?? k,
        p0: typeof pv === "number" && Number.isFinite(pv) ? pv : 0,
        lower: lv === null || lv === undefined ? null : (typeof lv === "number" && Number.isFinite(lv) ? lv : null),
        upper: uv === null || uv === undefined ? null : (typeof uv === "number" && Number.isFinite(uv) ? uv : null),
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
  };
}
