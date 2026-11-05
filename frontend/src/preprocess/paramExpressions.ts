/** F4 expression links: `{peak.param}` references (same grammar as core/preprocess/param_expressions.py). */
import type { FittingParamLink } from "./fittingUtils";

const REF_RE = /\{([^{}]+)\.([A-Za-z_][A-Za-z0-9_]*)\}/g;

export type ExprRef = { componentId: string; key: string };

/** `{A.pos}` references of an expression, unique, in order of appearance (id = text before the LAST dot). */
export function exprRefs(expr: string | undefined | null): ExprRef[] {
  const out: ExprRef[] = [];
  for (const m of String(expr ?? "").matchAll(REF_RE)) {
    const ref = { componentId: m[1]!.trim(), key: m[2]! };
    if (!out.some((r) => r.componentId === ref.componentId && r.key === ref.key)) out.push(ref);
  }
  return out;
}

/** Rename component ids inside the references of an expression. */
export function remapExprIds(expr: string, remap: (id: string) => string): string {
  return String(expr ?? "").replace(REF_RE, (_all, id: string, key: string) => `{${remap(id.trim())}.${key}}`);
}

export function isExprLink(link: Pick<FittingParamLink, "mode">): boolean {
  return link.mode === "expr";
}

/** Component ids a link follows: its target, or every peak referenced by its expression. */
export function linkDriverIds(link: FittingParamLink): string[] {
  if (isExprLink(link)) return [...new Set(exprRefs(link.expr).map((r) => r.componentId))];
  return link.target_component_id ? [link.target_component_id] : [];
}

/** Rename ids everywhere a link mentions them (source, target, expression references). */
export function remapLink(link: FittingParamLink, remap: (id: string) => string): FittingParamLink {
  const out: FittingParamLink = { ...link, source_component_id: remap(link.source_component_id) };
  if (isExprLink(link)) out.expr = remapExprIds(link.expr ?? "", remap);
  else out.target_component_id = remap(link.target_component_id);
  return out;
}

/** Colour of the peak a linked field follows (plot colour); neutral grey for several drivers or unknown peaks. */
export function linkColor(link: FittingParamLink, peakColors: Map<string, string>): string {
  const ids = linkDriverIds(link);
  return ids.length === 1 ? peakColors.get(ids[0]!) ?? "#7f8c8d" : "#7f8c8d";
}

/** True when the link's source and every peak it follows are in `ids`. */
export function linkUsesOnly(link: FittingParamLink, ids: Set<string>): boolean {
  return ids.has(link.source_component_id) && linkDriverIds(link).every((id) => ids.has(id));
}
