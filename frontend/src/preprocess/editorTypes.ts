import type { PipelineInputFrom } from "./api";

export type EditorStep = {
  id: string;
  name: string;
  enabled: boolean;
  params: Record<string, unknown>;
  input_from: PipelineInputFrom;
  after_step_id: string | null;
};

export type FieldSpec =
  | { key: string; kind: "number" | "int" | "boolean" | "string"; label: string; description?: string; nullable?: boolean }
  | { key: string; kind: "select"; label: string; options: string[]; description?: string; nullable?: boolean };

export function sanitizeStepInputs(steps: EditorStep[]): EditorStep[] {
  const byId = new Map(steps.map((s, i) => [s.id, i] as const));
  return steps.map((s, j) => {
    if (s.input_from !== "after_step") return { ...s, after_step_id: null };
    const aid = (s.after_step_id || "").trim();
    if (!aid) return { ...s, input_from: "previous", after_step_id: null };
    const k = byId.get(aid);
    if (k === undefined || k >= j) return { ...s, input_from: "previous", after_step_id: null };
    return { ...s, after_step_id: aid };
  });
}

/**
 * Legacy metadata_filter cleanup when loading a saved pipeline:
 * - Old UI always wrote action="exclude" while intending keep-matching.
 * Steps stay separate; each is a branch-local mask in the engine (respects input_from).
 * Multiple values in one step remain OR within that clause.
 */
export function migrateMetadataFilterStepsOnLoad(steps: EditorStep[]): EditorStep[] {
  return steps.map((s) => {
    if (s.name !== "metadata_filter") return s;
    const action = String(s.params?.action || "").trim().toLowerCase();
    if (action === "exclude" || !action) {
      return { ...s, params: { ...s.params, action: "keep" } };
    }
    return s;
  });
}

export function inputSelectValue(s: EditorStep): string {
  if (s.input_from === "initial") return "initial";
  if (s.input_from === "after_step" && (s.after_step_id || "").trim()) return `after:${s.after_step_id!.trim()}`;
  return "previous";
}

export function parseInputSelectValue(raw: string): { input_from: PipelineInputFrom; after_step_id: string | null } {
  if (raw === "initial") return { input_from: "initial", after_step_id: null };
  if (raw.startsWith("after:")) {
    const id = raw.slice("after:".length).trim();
    return id ? { input_from: "after_step", after_step_id: id } : { input_from: "previous", after_step_id: null };
  }
  return { input_from: "previous", after_step_id: null };
}
