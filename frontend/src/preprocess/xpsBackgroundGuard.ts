/** Detect static XPS baseline + active fit background conflict. */
export function dualXpsBackgroundConflict(steps: Array<{ name: string; enabled?: boolean; params?: Record<string, unknown> }>): string | null {
  const staticMethods = new Set<string>();
  const active = new Set<string>();
  for (const step of steps) {
    if (step.enabled === false) continue;
    const name = String(step.name || "").trim().toLowerCase();
    const params = (step.params ?? {}) as Record<string, unknown>;
    if (name === "baseline") {
      const method = String(params.method || "").trim().toLowerCase();
      if (method === "shirley" || method === "tougaard") staticMethods.add(method);
    } else if (name === "fitting") {
      const comps = params.components;
      if (!Array.isArray(comps)) continue;
      for (const row of comps) {
        if (!row || typeof row !== "object") continue;
        const ct = String((row as { component_type?: string }).component_type || "")
          .trim()
          .toLowerCase();
        if (ct === "shirley_bg" || ct === "tougaard_bg") active.add(ct);
      }
    }
  }
  if (staticMethods.size && active.size) {
    return (
      `Cannot combine static XPS baseline (${[...staticMethods].sort().join(", ")}) with ` +
      `active fit background (${[...active].sort().join(", ")}). ` +
      `Use either a baseline step Shirley/Tougaard or an active shirley_bg/tougaard_bg in fitting, not both.`
    );
  }
  return null;
}
