/**
 * spectral_intensities step params — must match backend parse_probes (intensity_probes.py).
 */

export type SpectralProbeEditorRow = {
  id: string;
  target_cm1: number;
  acquisition: "fixed" | "nearest_peak";
  method: "nearest" | "linear_interp";
  extrapolation: "nan" | "clip";
  /** Empty string = omit window (backend default). */
  window_cm1: number | "";
  no_peak_fallback: "none" | "fixed_nearest";
};

export function defaultSpectralIntensitiesParams(): { probes: SpectralProbeEditorRow[] } {
  return {
    probes: [defaultProbeRow(0)],
  };
}

export function defaultProbeRow(index: number): SpectralProbeEditorRow {
  return {
    id: index === 0 ? "p1" : `p${index + 1}`,
    target_cm1: 1000,
    acquisition: "fixed",
    method: "linear_interp",
    extrapolation: "nan",
    window_cm1: "",
    no_peak_fallback: "none",
  };
}

function asStr(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function asNum(v: unknown, fallback: number): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function probesFromParams(params: Record<string, unknown> | null | undefined): SpectralProbeEditorRow[] {
  const raw = params?.probes;
  if (!Array.isArray(raw) || raw.length === 0) {
    return [defaultProbeRow(0)];
  }
  return raw.map((row, i) => probeFromApi(row, i));
}

function probeFromApi(row: unknown, index: number): SpectralProbeEditorRow {
  if (!row || typeof row !== "object") return defaultProbeRow(index);
  const o = row as Record<string, unknown>;
  const w = o.window_cm1;
  let window_cm1: number | "" = "";
  if (w !== null && w !== undefined && w !== "") {
    const n = typeof w === "number" ? w : Number(w);
    if (Number.isFinite(n)) window_cm1 = n;
  }
  const acq = asStr(o.acquisition).toLowerCase();
  const acquisition: SpectralProbeEditorRow["acquisition"] = acq === "nearest_peak" ? "nearest_peak" : "fixed";
  const methodRaw = asStr(o.method).toLowerCase();
  const method: SpectralProbeEditorRow["method"] = methodRaw === "nearest" ? "nearest" : "linear_interp";
  const extRaw = asStr(o.extrapolation).toLowerCase();
  const extrapolation: SpectralProbeEditorRow["extrapolation"] = extRaw === "clip" ? "clip" : "nan";
  const fbRaw = asStr(o.no_peak_fallback).toLowerCase();
  const no_peak_fallback: SpectralProbeEditorRow["no_peak_fallback"] =
    fbRaw === "fixed_nearest" ? "fixed_nearest" : "none";

  return {
    id: asStr(o.id),
    target_cm1: asNum(o.target_cm1, 1000),
    acquisition,
    method,
    extrapolation,
    window_cm1,
    no_peak_fallback,
  };
}

export function probesToApiParams(probes: SpectralProbeEditorRow[]): Record<string, unknown> {
  const list = probes.map((row) => probeToApi(row));
  return { probes: list };
}

function probeToApi(row: SpectralProbeEditorRow): Record<string, unknown> {
  const o: Record<string, unknown> = {
    target_cm1: row.target_cm1,
    acquisition: row.acquisition,
    method: row.method,
    extrapolation: row.extrapolation,
    no_peak_fallback: row.no_peak_fallback,
    peak_find: {},
  };
  const id = row.id.trim();
  if (id) o.id = id;
  if (row.acquisition === "nearest_peak" && row.window_cm1 !== "" && typeof row.window_cm1 === "number") {
    o.window_cm1 = row.window_cm1;
  }
  return o;
}
