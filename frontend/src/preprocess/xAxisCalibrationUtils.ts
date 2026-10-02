import type { EditorStep } from "./editorTypes";
import { FALLBACK_PEAK_KEYS, isPeakComponentType } from "./fittingUtils";

export type XAxisCalibrationMethod =
  | "fixed_offset"
  | "single_reference_band"
  | "grouped_reference_band"
  | "reference_peak"; // legacy alias of single_reference_band

export type XAxisReferenceMode = "core_level" | "valence_band";

export type XAxisReferenceFilter = {
  field: string;
  op: string;
  values?: string[];
  value?: number;
};

export type XAxisCalibrationParams = {
  method: XAxisCalibrationMethod;
  offset: number;
  fitting_step_id: string;
  pos_key: string;
  target_x: number;
  reference_filters: XAxisReferenceFilter[];
  group_by: string;
  reference_mode: XAxisReferenceMode;
  reference_region: string;
};

function asStr(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function finiteNumber(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function safeFragment(id: string, fallback: string): string {
  return id.trim().replace(/[^a-zA-Z0-9_]+/g, "_") || fallback;
}

/** Strip optional feature-export ``s{N}_`` prefix; calibration keys are step-local. */
export function canonicalizeCalibrationPosKey(posKey: string): string {
  return String(posKey || "")
    .trim()
    .replace(/^s\d+_(?=fit_)/, "");
}

export function normalizeRegionToken(name: string | null | undefined): string {
  return String(name ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "");
}

export function isValenceBandRegionName(name: string | null | undefined): boolean {
  const s = String(name ?? "").trim().toLowerCase();
  if (!s) return false;
  return s.includes("valence") || s.includes("fermi") || s.includes("vb");
}

export function isValencePartnerForRegion(
  vbRegion: string | null | undefined,
  coreRegion: string | null | undefined
): boolean {
  if (!isValenceBandRegionName(vbRegion)) return false;
  const token = normalizeRegionToken(coreRegion);
  if (!token) return false;
  return normalizeRegionToken(vbRegion).includes(token);
}

function normalizeFilters(raw: unknown): XAxisReferenceFilter[] {
  if (!Array.isArray(raw)) return [];
  const out: XAxisReferenceFilter[] = [];
  for (const row of raw) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const field = asStr(r.field).trim();
    if (!field) continue;
    const op = asStr(r.op).trim() || "in";
    const filter: XAxisReferenceFilter = { field, op };
    if (Array.isArray(r.values)) filter.values = r.values.map((v) => String(v));
    if (typeof r.value === "number" && Number.isFinite(r.value)) filter.value = r.value;
    out.push(filter);
  }
  return out;
}

function normalizeMethod(raw: string): XAxisCalibrationMethod {
  const m = raw.trim().toLowerCase();
  if (m === "single_reference_band") return "single_reference_band";
  if (m === "grouped_reference_band") return "grouped_reference_band";
  if (m === "reference_peak") return "reference_peak";
  return "fixed_offset";
}

/** Default params; XPS pipelines should pass target_x=284.8 via defaultXAxisCalibrationParams. */
export function defaultXAxisCalibrationParams(
  techniqueFamily: "vibrational" | "xps" = "vibrational"
): XAxisCalibrationParams {
  return {
    method: "fixed_offset",
    offset: 0,
    fitting_step_id: "",
    pos_key: "",
    target_x: techniqueFamily === "xps" ? 284.8 : 0,
    reference_filters: [],
    group_by: "",
    reference_mode: "core_level",
    reference_region: "",
  };
}

export function normalizeXAxisCalibrationParams(
  params: Record<string, unknown> | null | undefined,
  techniqueFamily: "vibrational" | "xps" = "vibrational"
): XAxisCalibrationParams {
  const p = params ?? {};
  const method = normalizeMethod(asStr(p.method));
  const defaults = defaultXAxisCalibrationParams(techniqueFamily);
  const reference_mode: XAxisReferenceMode =
    asStr(p.reference_mode).trim().toLowerCase() === "valence_band" ? "valence_band" : "core_level";
  return {
    method,
    offset: finiteNumber(p.offset, defaults.offset),
    fitting_step_id: asStr(p.fitting_step_id).trim(),
    pos_key: canonicalizeCalibrationPosKey(asStr(p.pos_key)),
    target_x: finiteNumber(p.target_x, defaults.target_x),
    reference_filters: normalizeFilters(p.reference_filters),
    group_by: asStr(p.group_by).trim(),
    reference_mode,
    reference_region: asStr(p.reference_region).trim(),
  };
}

export function isCohortCalibrationMethod(method: string): boolean {
  const m = method.trim().toLowerCase();
  return m === "single_reference_band" || m === "grouped_reference_band" || m === "reference_peak";
}

/**
 * Position / Fermi-center keys for x_axis_calibration (always step-local, never s{N}_-prefixed).
 * Matches backend ``calibration_pos_keys_for_step``.
 */
export function fittingPosKeysForStep(step: EditorStep): string[] {
  const params = (step.params ?? {}) as Record<string, unknown>;
  const comps = params.components;
  if (!Array.isArray(comps)) return [];
  const regionRaw = asStr(params.xps_region).trim();
  const region = regionRaw ? safeFragment(regionRaw, "") : "";
  const mid = region ? `${region}_` : "";
  const keys: string[] = [];
  comps.forEach((row, i) => {
    if (!row || typeof row !== "object") return;
    const o = row as Record<string, unknown>;
    const id = safeFragment(asStr(o.component_id), `comp${i + 1}`);
    const type = asStr(o.component_type).toLowerCase();
    if (type === "polynomial_background") return;
    if (type === "shirley_bg" || type === "tougaard_bg" || type === "slope_bg") return;
    if (type === "fermi_edge") {
      keys.push(`fit_${mid}${id}_center`);
      return;
    }
    let paramKeys: string[] = [];
    if (isPeakComponentType(type)) {
      paramKeys = [...FALLBACK_PEAK_KEYS[type]];
    } else {
      paramKeys = ["pos", "amp", "fwhm"];
    }
    for (const pk of paramKeys) {
      if (pk === "pos") {
        keys.push(`fit_${mid}${id}_pos`);
      }
    }
  });
  return keys;
}

export function earlierFittingStepOptions(
  steps: EditorStep[],
  selectedStepId: string
): { step: EditorStep; index: number }[] {
  const selectedIndex = steps.findIndex((s) => s.id === selectedStepId);
  const earlier = steps.slice(0, Math.max(selectedIndex, 0));
  return earlier
    .map((step, index) => ({ step, index }))
    .filter(({ step }) => step.enabled !== false && step.name === "fitting");
}
