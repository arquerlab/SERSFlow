export type ReferenceOperation = "subtract" | "divide";
export type ReferenceStage = "raw" | "after_step";

export type ReferenceTransformParams = {
  reference_spectrum_id: string;
  reference_stage: ReferenceStage;
  reference_step_id: string;
  operation: ReferenceOperation;
  interpolation: "linear";
};

export function defaultReferenceTransformParams(): ReferenceTransformParams {
  return {
    reference_spectrum_id: "",
    reference_stage: "raw",
    reference_step_id: "",
    operation: "subtract",
    interpolation: "linear",
  };
}

function asStr(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

export function referenceTransformFromParams(
  params: Record<string, unknown> | null | undefined
): ReferenceTransformParams {
  const p = params ?? {};
  const operationRaw = asStr(p.operation).toLowerCase();
  const stageRaw = asStr(p.reference_stage).toLowerCase();
  return {
    reference_spectrum_id: asStr(p.reference_spectrum_id),
    reference_stage: stageRaw === "after_step" ? "after_step" : "raw",
    reference_step_id: asStr(p.reference_step_id),
    operation: operationRaw === "divide" ? "divide" : "subtract",
    interpolation: "linear",
  };
}

export function referenceTransformToApiParams(params: ReferenceTransformParams): Record<string, unknown> {
  const out: Record<string, unknown> = {
    reference_spectrum_id: params.reference_spectrum_id,
    reference_stage: params.reference_stage,
    operation: params.operation,
    interpolation: "linear",
  };
  if (params.reference_stage === "after_step") {
    out.reference_step_id = params.reference_step_id;
  }
  return out;
}
