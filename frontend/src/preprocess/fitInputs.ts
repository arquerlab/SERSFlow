/** Spectra the Prepare fitting preview last fitted (input to the fitting step), shared with S1 / M1 panels. */
export type FitPreviewInput = {
  spectrum_id: string;
  x: number[];
  y: number[];
  var?: number[] | null;
  var_kind?: "absolute" | "relative" | null;
};

/** Tougaard cross-section presets (B1): only U2 is in the project literature; others are entered by the user. */
export const TOUGAARD_PRESETS: Array<{ id: string; label: string; values: Record<string, number> }> = [
  { id: "u2", label: "U2 universal (metals): B 2866, C 1643", values: { B: 2866, C: 1643, C_d: 1, D: 0, T0: 0 } },
];

/** Inline fit target (with counting variance when the preview carried it, F1). */
export function inlineTarget(it: FitPreviewInput) {
  return {
    kind: "inline" as const,
    x: it.x,
    y: it.y,
    ...(Array.isArray(it.var) && it.var.length === it.y.length
      ? { y_variance: it.var, variance_kind: (it.var_kind ?? "relative") as "absolute" | "relative" }
      : {}),
  };
}
