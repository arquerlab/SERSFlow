import { describe, expect, it } from "vitest";
import { summarizeAcquisition } from "./AcquisitionSummary";

describe("summarizeAcquisition", () => {
  it("is null when no block carries IO1 labels (older imports)", () => {
    expect(summarizeAcquisition([{ vms_spectra: { "0": { xps_region: "C1s" } } }, null])).toBeNull();
  });

  it("counts units, ranges and transmission across files", () => {
    const s = summarizeAcquisition([
      {
        vms_spectra: {
          "0": { y_unit: "counts", dwell_time_s: 0.1, n_scans: 5, aux_arrays: ["transmission"] },
          "1": { y_unit: "cps", dwell_time_s: 0.2, n_scans: 10 },
        },
      },
      { vms_spectra: { "0": { y_unit: "weird" } } },
    ]);
    expect(s).not.toBeNull();
    expect(s!.nBlocks).toBe(3);
    expect(s!.byUnit).toEqual({ counts: 1, cps: 1, unknown: 1 });
    expect(s!.dwellRange).toEqual([0.1, 0.2]);
    expect(s!.scansRange).toEqual([5, 10]);
    expect(s!.nWithTransmission).toBe(1);
  });
});
