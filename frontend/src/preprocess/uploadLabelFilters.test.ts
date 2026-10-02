import { describe, expect, it } from "vitest";
import {
  distinctLabelValues,
  matchesLabelFilters,
  matchesLabelSelections,
  visibleFilterKeys,
} from "./uploadLabelFilters";

describe("uploadLabelFilters", () => {
  const items = [
    { labels: { sample: "Cu", ph: 7 } },
    { labels: { sample: "Au", gas: "Ar" } },
    { labels: {} },
  ];

  it("matches eq and exists filters with AND semantics", () => {
    expect(matchesLabelFilters({ sample: "Cu", ph: 7 }, [{ id: "1", key: "sample", op: "eq", value: "Cu" }])).toBe(true);
    expect(matchesLabelFilters({ sample: "Au" }, [{ id: "1", key: "sample", op: "eq", value: "Cu" }])).toBe(false);
    expect(matchesLabelFilters({ gas: "Ar" }, [{ id: "1", key: "gas", op: "exists" }])).toBe(true);
    expect(matchesLabelFilters({}, [{ id: "1", key: "gas", op: "exists" }])).toBe(false);
    expect(
      matchesLabelFilters(
        { sample: "Cu", ph: 7 },
        [
          { id: "1", key: "sample", op: "eq", value: "Cu" },
          { id: "2", key: "ph", op: "contains", value: "7" },
        ]
      )
    ).toBe(true);
  });

  it("matches Excel-style multi-select filters", () => {
    expect(matchesLabelSelections({ sample: "Cu", ph: 7 }, { sample: ["Cu", "Au"] })).toBe(true);
    expect(matchesLabelSelections({ sample: "Pt" }, { sample: ["Cu", "Au"] })).toBe(false);
    expect(matchesLabelSelections({ sample: "Cu", gas: "Ar" }, { sample: ["Cu"], gas: ["Ar"] })).toBe(true);
    expect(matchesLabelSelections({ sample: "Cu", gas: "N2" }, { sample: ["Cu"], gas: ["Ar"] })).toBe(false);
    expect(matchesLabelSelections({ sample: "Cu" }, { gas: [] })).toBe(true);
  });

  it("returns distinct label values", () => {
    expect(distinctLabelValues(items, "sample")).toEqual(["Au", "Cu"]);
  });

  it("OR-matches across vms_spectra blocks", () => {
    const labels = {
      sample: "pathOnly",
      vms_spectra: {
        "0": { xps_region: "C1s", potential_V: -0.2 },
        "1": { xps_region: "O1s", current_density_A_cm2: 0.05 },
      },
    };
    // Path has no potential_V; block 0 does → file matches
    expect(matchesLabelSelections(labels, { potential_V: ["-0.2"] })).toBe(true);
    expect(matchesLabelSelections(labels, { current_density_A_cm2: ["0.05"] })).toBe(true);
    expect(matchesLabelSelections(labels, { potential_V: ["-0.9"] })).toBe(false);
    // Distinct includes block-only keys
    expect(distinctLabelValues([{ labels }], "potential_V")).toEqual(["-0.2"]);
    expect(distinctLabelValues([{ labels }], "current_density_A_cm2")).toEqual(["0.05"]);
    expect(distinctLabelValues([{ labels }], "sample")).toEqual(["pathOnly"]);
  });

  it("visibleFilterKeys hides laser on XPS and empty gas/ph; expands electrochem trio", () => {
    const xpsItems = [
      {
        technique_family: "xps" as const,
        labels: {
          sample: "Cu",
          laser_nm: 785,
          potential_V: -0.1,
          vms_spectra: { "0": { current_density_A_cm2: 0.01, xps_region: "C1s" } },
        },
      },
    ];
    const keys = visibleFilterKeys(xpsItems, "xps");
    expect(keys).toContain("xps_region");
    expect(keys).toContain("sample");
    expect(keys).toContain("potential_V");
    expect(keys).toContain("potential_ref");
    expect(keys).toContain("current_density_A_cm2");
    expect(keys).not.toContain("laser_nm");
    expect(keys).not.toContain("gas");
    expect(keys).not.toContain("ph");

    const vib = visibleFilterKeys(
      [{ technique_family: "vibrational", labels: { laser_nm: 785, sample: "Au" } }],
      "vibrational"
    );
    expect(vib).toContain("laser_nm");
    expect(vib).toContain("sample");
    expect(vib).not.toContain("potential_V");
    expect(vib).not.toContain("xps_region");
  });
});
