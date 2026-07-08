import { describe, expect, it } from "vitest";
import { distinctLabelValues, matchesLabelFilters, matchesLabelSelections } from "./uploadLabelFilters";

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
});
