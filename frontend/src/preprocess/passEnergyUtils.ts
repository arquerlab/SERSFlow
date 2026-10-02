/** Prefer exact match, else closest pass energy (eV). */
export function preferPassEnergy(
  passEnergies: number[],
  preferred: number | null | undefined
): number | undefined {
  const pes = passEnergies.filter((pe) => Number.isFinite(pe));
  if (!pes.length) return undefined;
  if (preferred != null && Number.isFinite(preferred)) {
    if (pes.includes(preferred)) return preferred;
    return pes.reduce((best, pe) =>
      Math.abs(pe - preferred) < Math.abs(best - preferred) ? pe : best
    );
  }
  if (pes.includes(20)) return 20;
  return pes[0];
}
