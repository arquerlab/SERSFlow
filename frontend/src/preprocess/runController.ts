import type { SessionRunRequest, SessionRunReturnSpec } from "./api";

export type Mode = "explore" | "batch";
export type PlotView = "raw" | "final" | `after:${string}`;

export type RunControllerState = {
  mode: Mode;
  subsetCount: number;
  plotView: PlotView;
  upToStep: string | null;
  // For intermediates: which step(s) to collect.
  collectSteps: string[];
  batchMetrics: string[];
};

export type RunGuardrails = {
  maxPlotSpectraDefault: number; // e.g. 15
  maxPlotSpectraHardCap: number; // e.g. 30
  maxIntermediatesSubset: number; // backend hard-caps at 50
};

export const DEFAULT_GUARDRAILS: RunGuardrails = {
  maxPlotSpectraDefault: 15,
  maxPlotSpectraHardCap: 30,
  maxIntermediatesSubset: 50,
};

function wantsIntermediates(plotView: PlotView): boolean {
  return typeof plotView === "string" && plotView.startsWith("after:");
}

export function buildSafeRunRequest(state: RunControllerState, g: RunGuardrails = DEFAULT_GUARDRAILS): SessionRunRequest {
  if (state.mode === "batch") {
    // IMPORTANT: never request intermediates for full dataset.
    // This would generate huge payloads (spectra × steps × arrays). The backend also caps intermediates to 50 spectra.
    const ret: SessionRunReturnSpec = { kind: "metrics_only", metrics: state.batchMetrics };
    return { scope: "all", return: ret, up_to_step: state.upToStep ?? null };
  }

  // Explore: subset processing only.
  if (wantsIntermediates(state.plotView)) {
    if (state.subsetCount > g.maxIntermediatesSubset) {
      // Auto-downgrade: still safe and predictable.
      return { scope: "subset", return: { kind: "final" }, up_to_step: state.upToStep ?? null };
    }
    const steps = (state.collectSteps || []).filter(Boolean);
    return { scope: "subset", return: { kind: "intermediates", steps: steps.length ? steps : [String(state.plotView).slice("after:".length)] }, up_to_step: state.upToStep ?? null };
  }

  return { scope: "subset", return: { kind: "final" }, up_to_step: state.upToStep ?? null };
}

export function capTraceCount<T>(items: T[], desired: number, g: RunGuardrails = DEFAULT_GUARDRAILS): T[] {
  const n = Math.max(1, Math.min(g.maxPlotSpectraHardCap, Number(desired) || g.maxPlotSpectraDefault));
  return items.slice(0, n);
}

