import { describe, expect, it } from "vitest";
import {
  defaultFittingEditorParams,
  flattenFittingForPipeline,
  migrateFittingParamsToEditor,
  normalizeWeighting,
  weightingAppliedText,
  weightingRequestText,
} from "./fittingUtils";

describe("F1 weighting in the fitting editor", () => {
  it("defaults to auto and does not write the key (keeps pipeline hashes)", () => {
    const fp = defaultFittingEditorParams(undefined);
    expect(normalizeWeighting(fp.weighting)).toBe("auto");
    const flat = flattenFittingForPipeline(fp) as Record<string, unknown>;
    expect("weighting" in flat).toBe(false);
    expect("residual_view" in flat).toBe(false);
  });

  it("round-trips a non-default weighting and residual view", () => {
    const fp = { ...defaultFittingEditorParams(undefined), weighting: "none" as const, residual_view: "normalised" as const };
    const flat = flattenFittingForPipeline(fp) as Record<string, unknown>;
    expect(flat.weighting).toBe("none");
    expect(flat.residual_view).toBe("normalised");
    const back = migrateFittingParamsToEditor(flat, undefined);
    expect(back.weighting).toBe("none");
    expect(back.residual_view).toBe("normalised");
  });

  it("describes requested and applied weighting", () => {
    expect(weightingRequestText("auto", "vibrational")).toContain("unweighted");
    expect(weightingRequestText(undefined, "xps")).toContain("Poisson");
    expect(weightingAppliedText({ weighting: "poisson", residual_std_normalised: 1.04 })).toBe(
      "Poisson (absolute) · residual STD (norm.) 1.04"
    );
    expect(weightingAppliedText({ weighting: "poisson_relative", poisson_gain: 0.37 })).toContain("gain g = 0.370");
    expect(weightingAppliedText({ weighting: "none" })).toBe("Unweighted");
  });
});
