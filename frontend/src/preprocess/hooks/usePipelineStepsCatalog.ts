import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "../../lib/http";
import type { FieldSpec } from "../editorTypes";

export type PipelineStepUiField = FieldSpec;

export type PipelineStepMethodUi = {
  id: string;
  label: string;
  defaults: Record<string, unknown>;
  fields: PipelineStepUiField[];
};

export type PipelineStepUiSchema = {
  method_param_key: string | null;
  methods: PipelineStepMethodUi[];
  common_fields: PipelineStepUiField[];
  custom_editor: string | null;
};

export type PipelineStepCatalogItem = {
  id: string;
  label: string;
  category: string;
  palette_group: string;
  description: string;
  ui: PipelineStepUiSchema;
  requires_technique: string[] | null;
  requires_capabilities: string[];
  excludes_capabilities: string[];
  validation_rules: string[];
  has_impl: boolean;
};

export type PipelineStepsResponse = { items: PipelineStepCatalogItem[] };

async function fetchPipelineSteps(opts: {
  techniqueFamily?: string | null;
  capabilities?: string[];
}): Promise<PipelineStepsResponse> {
  const params = new URLSearchParams();
  if (opts.techniqueFamily) params.set("technique_family", opts.techniqueFamily);
  for (const c of opts.capabilities ?? []) params.append("capability", c);
  const qs = params.toString();
  return fetchJson<PipelineStepsResponse>(`/meta/pipeline-steps${qs ? `?${qs}` : ""}`);
}

export function usePipelineStepsCatalog(opts?: {
  techniqueFamily?: string | null;
  capabilities?: string[];
  enabled?: boolean;
}) {
  const techniqueFamily = opts?.techniqueFamily ?? null;
  const capabilities = opts?.capabilities ?? [];
  const capsKey = capabilities.slice().sort().join(",");
  return useQuery({
    queryKey: ["meta", "pipeline-steps", techniqueFamily, capsKey],
    queryFn: () => fetchPipelineSteps({ techniqueFamily, capabilities }),
    enabled: opts?.enabled !== false,
    staleTime: 60 * 60_000,
  });
}

export type StepSpecsMap = Record<
  string,
  {
    methodLabel: string;
    methods: { id: string; label: string; defaults: Record<string, unknown>; fields: FieldSpec[] }[];
    commonFields?: FieldSpec[];
  }
>;

/** Convert API step list into the param-editor StepSpecsMap shape. */
export function stepSpecsFromCatalog(items: PipelineStepCatalogItem[] | undefined): StepSpecsMap {
  const out: StepSpecsMap = {};
  for (const it of items ?? []) {
    if (it.ui.custom_editor) continue;
    out[it.id] = {
      methodLabel: it.ui.method_param_key || "method",
      methods: (it.ui.methods ?? []).map((m) => ({
        id: m.id,
        label: m.label,
        defaults: m.defaults ?? {},
        fields: (m.fields ?? []) as FieldSpec[],
      })),
      commonFields: (it.ui.common_fields ?? []) as FieldSpec[],
    };
  }
  return out;
}

export function useStepSpecsMap(opts?: {
  techniqueFamily?: string | null;
  capabilities?: string[];
}) {
  const q = usePipelineStepsCatalog(opts);
  const specs = useMemo(() => stepSpecsFromCatalog(q.data?.items), [q.data?.items]);
  return { ...q, specs };
}
