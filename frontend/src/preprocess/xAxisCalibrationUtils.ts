import type { EditorStep } from "./editorTypes";
import { FALLBACK_PEAK_KEYS, isPeakComponentType } from "./fittingUtils";

export type XAxisCalibrationMethod = "fixed_offset" | "reference_peak";

export type XAxisCalibrationParams = {
  method: XAxisCalibrationMethod;
  offset: number;
  fitting_step_id: string;
  pos_key: string;
  target_x: number;
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

/** Default params; XPS pipelines should pass target_x=284.8 via defaultXAxisCalibrationParams. */
export function defaultXAxisCalibrationParams(techniqueFamily: "vibrational" | "xps" = "vibrational"): XAxisCalibrationParams {
  return {
    method: "fixed_offset",
    offset: 0,
    fitting_step_id: "",
    pos_key: "",
    target_x: techniqueFamily === "xps" ? 284.8 : 0,
  };
}

export function normalizeXAxisCalibrationParams(
  params: Record<string, unknown> | null | undefined,
  techniqueFamily: "vibrational" | "xps" = "vibrational"
): XAxisCalibrationParams {
  const p = params ?? {};
  const methodRaw = asStr(p.method).trim().toLowerCase();
  const method: XAxisCalibrationMethod = methodRaw === "reference_peak" ? "reference_peak" : "fixed_offset";
  const defaults = defaultXAxisCalibrationParams(techniqueFamily);
  return {
    method,
    offset: finiteNumber(p.offset, defaults.offset),
    fitting_step_id: asStr(p.fitting_step_id).trim(),
    pos_key: asStr(p.pos_key).trim(),
    target_x: finiteNumber(p.target_x, defaults.target_x),
  };
}

/**
 * Position feature keys for one fitting step, matching backend fitting_features naming
 * (optional s{stepIndex}_ prefix when multiFitting, optional xps_region mid-segment).
 */
export function fittingPosKeysForStep(
  step: EditorStep,
  opts: { stepIndex: number; multiFitting: boolean }
): string[] {
  const { stepIndex, multiFitting } = opts;
  const params = (step.params ?? {}) as Record<string, unknown>;
  const comps = params.components;
  if (!Array.isArray(comps)) return [];
  const regionRaw = asStr(params.xps_region).trim();
  const region = regionRaw ? safeFragment(regionRaw, "") : "";
  const prefix = multiFitting ? `s${stepIndex}_` : "";
  const mid = region ? `${region}_` : "";
  const keys: string[] = [];
  comps.forEach((row, i) => {
    if (!row || typeof row !== "object") return;
    const o = row as Record<string, unknown>;
    const id = safeFragment(asStr(o.component_id), `comp${i + 1}`);
    const type = asStr(o.component_type).toLowerCase();
    if (type === "polynomial_background") return;
    if (type === "shirley_bg" || type === "tougaard_bg" || type === "slope_bg") return;
    let paramKeys: string[] = [];
    if (isPeakComponentType(type)) {
      paramKeys = [...FALLBACK_PEAK_KEYS[type]];
    } else {
      paramKeys = ["pos", "amp", "fwhm"];
    }
    for (const pk of paramKeys) {
      if (pk === "pos") {
        keys.push(`${prefix}fit_${mid}${id}_pos`);
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

export function multiFittingInPipeline(steps: EditorStep[]): boolean {
  return steps.filter((s) => s.enabled !== false && s.name === "fitting").length > 1;
}
