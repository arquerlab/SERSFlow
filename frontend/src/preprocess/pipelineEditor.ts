import type { BaselineMethodsResponse, FittingComponentSpecPublic, NormalizeParams, Pipeline } from "./api";
import type { EditorStep } from "./editorTypes";
import { fallbackBaselineCatalog, normalizeBaselineParams } from "./baselineMethodCatalog";
import { flattenFittingForPipeline, migrateFittingParamsToEditor } from "./fittingUtils";
import { pipelineStepSpecs } from "./pipelineStepSpecs";

const DEFAULT_POINT_X = 1000;

function finiteNumber(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function normalizeNormalizeParams(params: Record<string, unknown> | null | undefined): NormalizeParams {
  const p = { ...(params ?? {}) };
  const method = String(p.method || "max");
  if (method === "baseline") {
    return {
      method: "spectrum_point",
      point_x: finiteNumber(p.point_x ?? p.baseline_point, DEFAULT_POINT_X),
    };
  }
  if (method === "spectrum_point") {
    return {
      method: "spectrum_point",
      point_x: finiteNumber(p.point_x ?? p.baseline_point, DEFAULT_POINT_X),
    };
  }
  if (method === "baseline_point") {
    return {
      method: "baseline_point",
      baseline_step_id: String(p.baseline_step_id ?? "").trim(),
      point_x: finiteNumber(p.point_x ?? p.baseline_point, DEFAULT_POINT_X),
    };
  }
  if (method === "min" || method === "mean" || method === "median" || method === "vector" || method === "l2") {
    return { method };
  }
  return { method: "max" };
}

export function normalizeMethodParams(
  stepName: string,
  params: Record<string, unknown> | null | undefined,
  fittingCatalog: FittingComponentSpecPublic[] | undefined,
  baselineCatalog: BaselineMethodsResponse = fallbackBaselineCatalog
): Record<string, unknown> {
  if (stepName === "fitting") {
    return migrateFittingParamsToEditor((params ?? {}) as Record<string, unknown>, fittingCatalog) as unknown as Record<
      string,
      unknown
    >;
  }
  if (stepName === "normalize") {
    return normalizeNormalizeParams(params);
  }
  if (stepName === "baseline") {
    return normalizeBaselineParams(params, baselineCatalog);
  }
  const spec = pipelineStepSpecs[stepName];
  if (!spec) return params ?? {};
  const p = { ...(params ?? {}) };
  const method = String(p.method || spec.methods[0]?.id || "");
  const def = spec.methods.find((m) => m.id === method) ?? spec.methods[0];
  if (!def) return p;
  return { method: def.id, ...def.defaults, ...Object.fromEntries(Object.entries(p).filter(([k]) => k !== "method")) };
}

export function editorStepsToApiSteps(
  slist: EditorStep[],
  fittingCatalog: FittingComponentSpecPublic[] | undefined,
  baselineCatalog: BaselineMethodsResponse = fallbackBaselineCatalog
): Pipeline["steps"] {
  return slist.map((s) => {
    const input_from = s.input_from ?? "previous";
    let paramsOut: Record<string, unknown>;
    if (s.name === "fitting") {
      const fp = migrateFittingParamsToEditor(s.params ?? {}, fittingCatalog);
      paramsOut = flattenFittingForPipeline(fp);
    } else {
      paramsOut = normalizeMethodParams(s.name, s.params, fittingCatalog, baselineCatalog);
    }
    const row: Record<string, unknown> = {
      name: s.name,
      params: paramsOut,
      enabled: s.enabled !== false,
      step_id: s.id,
      input_from,
    };
    if (input_from === "after_step" && (s.after_step_id || "").trim()) {
      row.after_step_id = String(s.after_step_id).trim();
    }
    return row as Pipeline["steps"][number];
  });
}

export function buildPipelineFromEditor(
  steps: EditorStep[],
  fittingCatalog: FittingComponentSpecPublic[] | undefined,
  baselineCatalog: BaselineMethodsResponse = fallbackBaselineCatalog
): Pipeline {
  return { steps: editorStepsToApiSteps(steps, fittingCatalog, baselineCatalog) };
}
