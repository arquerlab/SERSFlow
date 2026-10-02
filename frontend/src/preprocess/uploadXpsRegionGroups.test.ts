import { describe, expect, it } from "vitest";
import {
  buildXpsRegionGroupOptions,
  isTechniqueFamilyTie,
  majorityTechniqueFamily,
  selectionMixesTechniques,
} from "./uploadXpsRegionGroups";

describe("uploadXpsRegionGroups", () => {
  it("groups files by region and handles multi-region files", () => {
    const opts = buildXpsRegionGroupOptions([
      { relative_path: "a/c1s.vms", xps_regions: ["C1s"], spectrum_count: 2 },
      { relative_path: "a/mix.vms", xps_regions: ["C1s", "O1s"], spectrum_count: 5 },
      { relative_path: "a/unk.vms", xps_regions: [], spectrum_count: 1 },
    ]);
    const byKey = Object.fromEntries(opts.map((o) => [o.key, o]));
    expect(byKey.C1s?.paths).toEqual(["a/c1s.vms", "a/mix.vms"]);
    expect(byKey.O1s?.paths).toEqual(["a/mix.vms"]);
    expect(byKey.__unknown__?.paths).toEqual(["a/unk.vms"]);
    // Without block maps, selection keys are whole-file paths
    expect(byKey.C1s?.selectionKeys).toEqual(["a/c1s.vms", "a/mix.vms"]);
  });

  it("selects per-block keys when vms_spectra is present", () => {
    const opts = buildXpsRegionGroupOptions([
      {
        relative_path: "a/mix.vms",
        xps_regions: ["C1s", "O1s"],
        spectrum_count: 3,
        labels: {
          vms_spectra: {
            "0": { xps_region: "C1s" },
            "1": { xps_region: "C1s" },
            "2": { xps_region: "O1s" },
          },
        },
      },
    ]);
    const byKey = Object.fromEntries(opts.map((o) => [o.key, o]));
    expect(byKey.C1s?.selectionKeys).toEqual(["a/mix.vms#0", "a/mix.vms#1"]);
    expect(byKey.O1s?.selectionKeys).toEqual(["a/mix.vms#2"]);
    expect(byKey.C1s?.spectrumCount).toBe(2);
    expect(byKey.O1s?.spectrumCount).toBe(1);
  });

  it("majorityTechniqueFamily prefers vibrational on tie", () => {
    const tieItems = [
      { relative_path: "a.vms", technique_family: "xps" as const },
      { relative_path: "b.txt", technique_family: "vibrational" as const },
    ];
    expect(majorityTechniqueFamily(tieItems)).toBe("vibrational");
    expect(isTechniqueFamilyTie(tieItems)).toBe(true);
    expect(
      majorityTechniqueFamily([
        { relative_path: "a.vms", technique_family: "xps" },
        { relative_path: "b.vms", technique_family: "xps" },
        { relative_path: "c.txt", technique_family: "vibrational" },
      ])
    ).toBe("xps");
    expect(isTechniqueFamilyTie([{ relative_path: "a.vms", technique_family: "xps" }])).toBe(false);
  });

  it("selectionMixesTechniques detects mixed selection", () => {
    const items = [
      { relative_path: "a.vms", technique_family: "xps" as const },
      { relative_path: "b.txt", technique_family: "vibrational" as const },
    ];
    expect(selectionMixesTechniques(["a.vms"], items)).toBe(false);
    expect(selectionMixesTechniques(["a.vms", "b.txt"], items)).toBe(true);
  });
});
