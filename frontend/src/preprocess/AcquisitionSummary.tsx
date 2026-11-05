/**
 * IO1: what the VAMAS ordinate is for the dataset's spectra (counts vs counts/s, dwell, scans,
 * transmission function present), read from the per-block upload labels.
 */

type BlockLabels = {
  y_unit?: unknown;
  dwell_time_s?: unknown;
  n_scans?: unknown;
  aux_arrays?: unknown;
};

export type AcquisitionSummaryData = {
  nBlocks: number;
  byUnit: Record<"counts" | "cps" | "unknown", number>;
  dwellRange: [number, number] | null;
  scansRange: [number, number] | null;
  nWithTransmission: number;
};

function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function widen(r: [number, number] | null, v: number | null): [number, number] | null {
  if (v == null) return r;
  return r ? [Math.min(r[0], v), Math.max(r[1], v)] : [v, v];
}

/** Aggregate VAMAS block labels (`labels.vms_spectra`) of the given upload items. */
export function summarizeAcquisition(
  labelsList: Array<Record<string, unknown> | null | undefined>
): AcquisitionSummaryData | null {
  const out: AcquisitionSummaryData = {
    nBlocks: 0,
    byUnit: { counts: 0, cps: 0, unknown: 0 },
    dwellRange: null,
    scansRange: null,
    nWithTransmission: 0,
  };
  for (const labels of labelsList) {
    const blocks = labels?.vms_spectra as Record<string, BlockLabels> | undefined;
    if (!blocks || typeof blocks !== "object") continue;
    for (const b of Object.values(blocks)) {
      if (!b || typeof b !== "object" || b.y_unit === undefined) continue; // imported before IO1
      out.nBlocks += 1;
      const unit = b.y_unit === "counts" || b.y_unit === "cps" ? b.y_unit : "unknown";
      out.byUnit[unit] += 1;
      out.dwellRange = widen(out.dwellRange, num(b.dwell_time_s));
      out.scansRange = widen(out.scansRange, num(b.n_scans));
      if (Array.isArray(b.aux_arrays) && b.aux_arrays.includes("transmission")) out.nWithTransmission += 1;
    }
  }
  return out.nBlocks ? out : null;
}

function fmtRange(r: [number, number] | null, unit = ""): string {
  if (!r) return "—";
  const f = (v: number) => `${Number(v.toPrecision(4))}${unit}`;
  return r[0] === r[1] ? f(r[0]) : `${f(r[0])}–${f(r[1])}`;
}

export function AcquisitionSummary({ data }: { data: AcquisitionSummaryData | null }) {
  if (!data) return null;
  const { byUnit } = data;
  const units = (["counts", "cps", "unknown"] as const)
    .filter((u) => byUnit[u])
    .map((u) => `${byUnit[u]} ${u === "cps" ? "counts/s" : u === "unknown" ? "not count-based" : "counts"}`)
    .join(", ");
  return (
    <div className="hint" style={{ marginTop: "4px" }} data-testid="acquisition-summary">
      <div>
        <b>Ordinate:</b> {units} · <b>dwell</b> {fmtRange(data.dwellRange, " s")} · <b>scans</b>{" "}
        {fmtRange(data.scansRange)}
      </div>
      <div>
        <b>Transmission function in file:</b> {data.nWithTransmission} of {data.nBlocks} block(s)
      </div>
      {byUnit.unknown ? (
        <div className="warn-note" style={{ marginTop: 4 }}>
          {byUnit.unknown} block(s) are not raw counts (e.g. normalised intensity): Poisson statistics and
          CPS-based quantification cannot be derived for them.
        </div>
      ) : null}
    </div>
  );
}
