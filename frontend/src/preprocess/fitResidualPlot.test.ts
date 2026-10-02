import { describe, expect, it } from "vitest";
import {
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
});
