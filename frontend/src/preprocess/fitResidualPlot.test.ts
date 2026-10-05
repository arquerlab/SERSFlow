import { describe, expect, it } from "vitest";
import {
  buildFitResidualFigure,
  gapNumber,
  gapSeries,
  isBackgroundComponentType,
  peakOnBackground,
  sumBackgroundY,
} from "./fitResidualPlot";

describe("fitResidualPlot helpers", () => {
  it("detects background component types", () => {
    expect(isBackgroundComponentType("polynomial_background")).toBe(true);
    expect(isBackgroundComponentType("shirley_bg")).toBe(true);
    expect(isBackgroundComponentType("gaussian")).toBe(false);
  });

  it("sums background curves", () => {
    const { bgSum, hasBg } = sumBackgroundY(
      [
        { component_id: "bg", component_type: "polynomial_background", y_hat: [1, 2, 3] },
        { component_id: "pk", component_type: "gaussian", y_hat: [10, 10, 10] },
      ],
      3
    );
    expect(hasBg).toBe(true);
    expect(bgSum).toEqual([1, 2, 3]);
  });

  it("adds peak on background", () => {
    expect(peakOnBackground([5, 5], [1, 2])).toEqual([6, 7]);
  });

  it("preserves null/NaN gaps instead of coercing to zero", () => {
    expect(Number.isNaN(gapNumber(null))).toBe(true);
    expect(Number.isNaN(gapNumber(Number.NaN))).toBe(true);
    expect(gapNumber(3)).toBe(3);
    expect(gapSeries([1, null, 3])).toEqual([1, Number.NaN, 3]);

    const { bgSum } = sumBackgroundY(
      [{ component_id: "bg", component_type: "shirley_bg", y_hat: [10, null, 12] }],
      3
    );
    expect(bgSum[0]).toBe(10);
    expect(Number.isNaN(bgSum[1]!)).toBe(true);
    expect(bgSum[2]).toBe(12);

    const stacked = peakOnBackground([5, null, 7], [1, 2, 3]);
    expect(stacked[0]).toBe(6);
    expect(Number.isNaN(stacked[1]!)).toBe(true);
    expect(stacked[2]).toBe(10);
  });

  it("Fit (sum) keeps gaps so intensity does not drop to zero outside window", () => {
    const fig = buildFitResidualFigure({
      x: [1, 2, 3, 4],
      y: [10, 20, 30, 40],
      yHat: [null, 22, 28, null],
      residual: [null, -2, 2, null],
      components: [
        { component_id: "bg", component_type: "shirley_bg", y_hat: [null, 5, 5, null] },
        { component_id: "p1", component_type: "gl", y_hat: [null, 17, 23, null] },
      ],
    });
    const fit = fig.data.find((t) => t.name === "Fit (sum)") as { y: number[]; connectgaps?: boolean };
    expect(fit.connectgaps).toBe(false);
    expect(Number.isNaN(fit.y[0]!)).toBe(true);
    expect(fit.y[1]).toBe(22);
    expect(Number.isNaN(fit.y[3]!)).toBe(true);

    const peak = fig.data.find((t) => t.name === "gl [p1]") as { y: number[] };
    expect(Number.isNaN(peak.y[0]!)).toBe(true);
    expect(peak.y[1]).toBe(22); // peak + bg
    expect(Number.isNaN(peak.y[3]!)).toBe(true);
  });
});
