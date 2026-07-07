import type { EditorStep } from "./editorTypes";
import { integrationFeatureKeys } from "./spectralIntegrationsUtils";
import { probesFromParams } from "./spectralIntensitiesUtils";

export type FeatureOperationEditorRow = {
  id: string;
  formula: string;
};

export type FeatureVariable = {
  key: string;
  source: string;
};

export function defaultFeatureOperationRow(index: number): FeatureOperationEditorRow {
  return {
    id: index === 0 ? "ratio1" : `op${index + 1}`,
    formula: "",
  };
}

export function defaultFeatureOperationsParams(): { operations: FeatureOperationEditorRow[] } {
  return { operations: [defaultFeatureOperationRow(0)] };
}

function asStr(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

export function featureOperationsFromParams(
  params: Record<string, unknown> | null | undefined
): FeatureOperationEditorRow[] {
  const raw = params?.operations;
  if (!Array.isArray(raw) || raw.length === 0) {
    return [defaultFeatureOperationRow(0)];
  }
  return raw.map((row, i) => {
    if (!row || typeof row !== "object") return defaultFeatureOperationRow(i);
    const o = row as Record<string, unknown>;
    return {
      id: asStr(o.id),
      formula: asStr(o.formula),
    };
  });
}

export function featureOperationsToApiParams(operations: FeatureOperationEditorRow[]): Record<string, unknown> {
  return {
    operations: operations.map((row) => {
      const out: Record<string, unknown> = { formula: row.formula };
      const id = row.id.trim();
      if (id) out.id = id;
      return out;
    }),
  };
}

function safeFragment(id: string, fallback: string): string {
  return id.trim().replace(/[^a-zA-Z0-9_]+/g, "_") || fallback;
}

function fittingFeatureKeys(params: Record<string, unknown> | null | undefined): string[] {
  const comps = params?.components;
  if (!Array.isArray(comps)) return [];
  const keys: string[] = [];
  comps.forEach((row, i) => {
    if (!row || typeof row !== "object") return;
    const o = row as Record<string, unknown>;
    const id = safeFragment(asStr(o.component_id), `comp${i + 1}`);
    const type = asStr(o.component_type).toLowerCase();
    if (type === "polynomial_background") {
      const degree = Math.max(0, Math.floor(Number(o.degree ?? 2)));
      for (let d = degree; d >= 0; d -= 1) {
        keys.push(`fit_${id}_c${d}`);
      }
    } else {
      keys.push(`fit_${id}_pos`, `fit_${id}_amp`, `fit_${id}_fwhm`, `fit_${id}_area`);
    }
  });
  return keys;
}

function spectralIntensityFeatureKeys(params: Record<string, unknown> | null | undefined): string[] {
  return probesFromParams(params).flatMap((row, i) => {
    const id = safeFragment(row.id, `cm1_${String(row.target_cm1).replace(".", "d")}_${i}`);
    const keys = [`I_${id}`];
    if (row.acquisition === "nearest_peak") keys.push(`peak_pos_cm1_${id}`);
    return keys;
  });
}

function operationFeatureKeys(params: Record<string, unknown> | null | undefined): string[] {
  return featureOperationsFromParams(params).map((row, i) => `op_${safeFragment(row.id, `op${i + 1}`)}`);
}

export function featureVariablesBeforeStep(steps: EditorStep[], selectedStepId: string): FeatureVariable[] {
  const variables: FeatureVariable[] = [];
  for (const step of steps) {
    if (step.id === selectedStepId) break;
    if (step.enabled === false) continue;
    const params = (step.params ?? {}) as Record<string, unknown>;
    let keys: string[] = [];
    if (step.name === "fitting") keys = fittingFeatureKeys(params);
    else if (step.name === "spectral_intensities") keys = spectralIntensityFeatureKeys(params);
    else if (step.name === "spectral_integrations") keys = integrationFeatureKeys(params);
    else if (step.name === "feature_operations") keys = operationFeatureKeys(params);
    variables.push(...keys.map((key) => ({ key, source: step.name })));
  }
  return variables;
}
