import { describe, expect, it } from "vitest";
import {
  blockDisplayName,
  effectiveLabelRows,
  mergePathAndBlockLabels,
  pathLabelsWithoutInternal,
} from "./uploadBlockSpectra";

describe("uploadBlockSpectra", () => {
  it("strips internal keys from path labels", () => {
    const out = pathLabelsWithoutInternal({
      sample: "Cu",
      vms_spectra: { "0": { xps_region: "C1s" } },
      vms_spectrum_mode: "averages",
    });
    expect(out).toEqual({ sample: "Cu" });
    expect("vms_spectra" in out).toBe(false);
  });

  it("merges path and block with block winning", () => {
    const merged = mergePathAndBlockLabels(
      { sample: "path", gas: "Ar", vms_spectra: {} },
      { sample: "block", potential_V: -0.1 }
    );
    expect(merged.sample).toBe("block");
    expect(merged.gas).toBe("Ar");
    expect(merged.potential_V).toBe(-0.1);
  });

  it("effectiveLabelRows includes path and each block", () => {
    const rows = effectiveLabelRows({
      sample: "Cu",
      vms_spectra: {
        "1": { xps_region: "O1s", gas: "CO2" },
        "0": { xps_region: "C1s", potential_V: -0.2 },
      },
    });
    expect(rows).toHaveLength(3);
    expect(rows[0].sample).toBe("Cu");
    expect(rows[1].xps_region).toBe("C1s");
    expect(rows[2].gas).toBe("CO2");
  });

  it("blockDisplayName prefers block_name", () => {
    expect(blockDisplayName({ block_name: "C1s_avg" })).toBe("C1s_avg");
    expect(blockDisplayName({ xps_region: "O1s", spectrum_role: "individual" })).toBe("O1s · individual");
  });
});
