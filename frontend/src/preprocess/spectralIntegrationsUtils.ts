/**
 * spectral_integrations step params — must match backend integration_features.py.
 */

export type IntegrationMode = "signed" | "positive" | "absolute";

export type IntegrationWindowEditorRow = {
  id: string;
  min_cm1: number;
  max_cm1: number;
  mode: IntegrationMode;
};

export function defaultIntegrationRow(index: number): IntegrationWindowEditorRow {
  return {
    id: index === 0 ? "band1" : `band${index + 1}`,
    min_cm1: 1900,
    max_cm1: 2150,
    mode: "signed",
  };
}

export function defaultSpectralIntegrationsParams(): { windows: IntegrationWindowEditorRow[] } {
  return { windows: [defaultIntegrationRow(0)] };
}

function asStr(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function asNum(v: unknown, fallback: number): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function integrationWindowsFromParams(
  params: Record<string, unknown> | null | undefined
): IntegrationWindowEditorRow[] {
  const raw = params?.windows;
  if (!Array.isArray(raw) || raw.length === 0) {
    return [defaultIntegrationRow(0)];
  }
  return raw.map((row, i) => integrationWindowFromApi(row, i));
}

function integrationWindowFromApi(row: unknown, index: number): IntegrationWindowEditorRow {
  if (!row || typeof row !== "object") return defaultIntegrationRow(index);
  const o = row as Record<string, unknown>;
  const modeRaw = asStr(o.mode).toLowerCase();
  const mode: IntegrationMode = modeRaw === "positive" || modeRaw === "absolute" ? modeRaw : "signed";
  return {
    id: asStr(o.id),
    min_cm1: asNum(o.min_cm1, 1900),
    max_cm1: asNum(o.max_cm1, 2150),
    mode,
  };
}

export function integrationWindowsToApiParams(windows: IntegrationWindowEditorRow[]): Record<string, unknown> {
  return {
    windows: windows.map((row) => {
      const out: Record<string, unknown> = {
        min_cm1: row.min_cm1,
        max_cm1: row.max_cm1,
        mode: row.mode,
      };
      const id = row.id.trim();
      if (id) out.id = id;
      return out;
    }),
  };
}

export function integrationFeatureKeys(params: Record<string, unknown> | null | undefined): string[] {
  return integrationWindowsFromParams(params).map((row, i) => {
    const id = row.id.trim() || `band${i + 1}`;
    return `area_${id.replace(/[^a-zA-Z0-9_]+/g, "_") || "area"}`;
  });
}
