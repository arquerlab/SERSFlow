export function clampSplitWidth(width: number, minWidth: number, maxWidth: number): number {
  if (!Number.isFinite(width)) return minWidth;
  return Math.min(maxWidth, Math.max(minWidth, width));
}

export function readSplitWidth(storageKey: string, defaultWidth: number, minWidth: number, maxWidth: number): number {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw == null || raw === "") return defaultWidth;
    return clampSplitWidth(Number(raw), minWidth, maxWidth);
  } catch {
    return defaultWidth;
  }
}

export function writeSplitWidth(storageKey: string, width: number): void {
  try {
    localStorage.setItem(storageKey, String(Math.round(width)));
  } catch {
    // ignore
  }
}
