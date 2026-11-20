import { describe, expect, it } from "vitest";
import { boundaryScatterFigure, costFigure, labelCsvRows, profileFigure, signatureCsvRows } from "./segmentsPlots";
import type { SegmentsResult } from "./segmentsApi";

const res: SegmentsResult = {
  method: "contiguous",
  n_segments: 2,
  n_rows: 4,
  n_dropped_rows: 0,
  order_column: "axis_z",
  feature_columns: ["a"],
  cuts: [5],
  cost_by_k: { "1": 10, "2": 2 },
  per_position_cuts: [{ position: [0, 0], cuts: [4] }, { position: [1, 0], cuts: [6] }],
  segments: [
    { segment: 0, n: 2, z_min: 0, z_max: 0, z_median: 0, median_features: { a: 1 } },
    { segment: 1, n: 2, z_min: 10, z_max: 10, z_median: 10, median_features: { a: 3 } },
  ],
  zone_names: ["low", "high"],
  spectrum_ids: ["s0", "s1", "s2", "s3"],
  labels: [0, 0, 1, 1],
  z_used: [0, 0, 10, 10],
  z_original: [0, 0, 10, 10],
};

describe("segmentsPlots", () => {
  it("builds cost, boundary and profile figures", () => {
    expect(costFigure(res).data).toHaveLength(1);
    expect(boundaryScatterFigure(res)?.data).toHaveLength(1);
    const f = profileFigure(res, [1, 1, 3, 3], "a", 5, ["low", "high"]);
    expect((f.layout.shapes as unknown[]).length).toBe(2);
  });
  it("exports labels with zone names and signatures", () => {
    const rows = labelCsvRows(res, ["low", "high"]);
    expect(rows[2]).toMatchObject({ spectrum_id: "s2", segment: 2, zone: "high" });
    expect(signatureCsvRows(res, ["low", "high"])[0]).toEqual({ feature: "a", low: 1, high: 3 });
  });
});
