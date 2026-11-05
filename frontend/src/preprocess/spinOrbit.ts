/** F3 spin-orbit doublet helpers (labels only; the server builds the links). */

export type Subshell = "p" | "d" | "f";

/** area(low j) / area(high j) = (2j+1) ratio: 2p 1:2, 3d 2:3, 4f 3:4. */
export const SUBSHELL_AREA_RATIO: Record<Subshell, number> = { p: 1 / 2, d: 2 / 3, f: 3 / 4 };

export const SUBSHELL_LABELS: Record<Subshell, string> = {
  p: "p (3/2 + 1/2, area 2:1)",
  d: "d (5/2 + 3/2, area 3:2)",
  f: "f (7/2 + 5/2, area 4:3)",
};

/** Subshell from a peak name or region (e.g. "Co_2p3/2", "4f7_2", "Ag 3d"); null when none is named. */
export function guessSubshell(...texts: Array<string | null | undefined>): Subshell | null {
  for (const t of texts) {
    const m = /[1-7]([pdf])(?![a-z])/i.exec(String(t ?? ""));
    if (m) return m[1]!.toLowerCase() as Subshell;
  }
  return null;
}

/** Whether a component already looks like the low-j member (2p1/2, 3d3/2, 4f5/2) of a doublet. */
export function isLowJComponentId(id: string): boolean {
  return /[1-7](p1|d3|f5)[_/]?2(?![0-9])/i.test(id);
}
