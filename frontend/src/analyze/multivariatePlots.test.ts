import { describe, expect, it } from "vitest";
import { buildCorrelationHeatmap, buildCosMap, buildNmfScan, compactPreprocess } from "./multivariatePlots";

describe("compactPreprocess", () => {
  it("returns null when everything is default", () => {
    expect(compactPreprocess({ bin: 1, row_norm: "none", center: "mean", scale: "none", derivative: 0, smooth_window: 0 })).toBeNull();
  });
  it("keeps only changed fields", () => {
    const p = compactPreprocess({ crop: [200, 900], bin: 2, row_norm: "snv", scale: "pareto", nonneg: "clip", center: "none" });
    expect(p).toEqual({ crop: [200, 900], bin: 2, row_norm: "snv", scale: "pareto", nonneg: "clip", center: "none" });
  });
  it("sends smoothing as a group", () => {
    expect(compactPreprocess({ derivative: 1 })).toMatchObject({ derivative: 1, smooth_window: 0, smooth_poly: 3 });
  });
});

describe("figure builders", () => {
  it("builds a symmetric correlation heatmap", () => {
    const fig = buildCorrelationHeatmap({
      method: "pearson",
      axis: "channels",
      labels: ["a", "b"],
      R: [[1, 0.5], [0.5, 1]],
      reordered: true,
      linkage: "average",
    });
    expect(fig.data[0].zmin).toBe(-1);
    expect(String(fig.layout.title.text)).toContain("clustered");
  });
  it("scales the 2D-COS colour range symmetrically", () => {
    const fig = buildCosMap(
      {
        x_cm1: [1, 2],
        synchronous: [[2, -4], [-4, 1]],
        asynchronous: [[0, 1], [-1, 0]],
        autopower: [2, 1],
        reference_spectrum: [1, 1],
        perturbation: [0, 1, 2],
        perturbation_label: "sample order",
        n_spectra: 3,
        resampled: false,
      },
      "synchronous"
    );
    expect(fig.data[0].zmax).toBe(4);
    expect(fig.data[0].zmin).toBe(-4);
  });
  it("returns null for a scan with one point", () => {
    expect(
      buildNmfScan({ n_components: 2, scores: [], components: [], x_cm1: [], spectrum_ids: [], scan: [{ k: 2, reconstruction_error: 1, lack_of_fit_pct: 1 }] })
    ).toBeNull();
  });
});
