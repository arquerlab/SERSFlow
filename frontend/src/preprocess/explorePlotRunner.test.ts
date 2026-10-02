import { describe, expect, it } from "vitest";
import { parseAfterPlotToken } from "./explorePlotRunner";

describe("parseAfterPlotToken", () => {
  it("parses plain step names", () => {
    expect(parseAfterPlotToken("fitting")).toEqual({ name: "fitting", stepNum: null });
    expect(parseAfterPlotToken("baseline")).toEqual({ name: "baseline", stepNum: null });
  });

  it("splits name__stepNum without swallowing underscores in the name", () => {
    expect(parseAfterPlotToken("fitting__3")).toEqual({ name: "fitting", stepNum: 3 });
    expect(parseAfterPlotToken("baseline__12")).toEqual({ name: "baseline", stepNum: 12 });
    expect(parseAfterPlotToken("x_axis_calibration__2")).toEqual({
      name: "x_axis_calibration",
      stepNum: 2,
    });
  });

  it("handles null/empty", () => {
    expect(parseAfterPlotToken(null)).toEqual({ name: null, stepNum: null });
    expect(parseAfterPlotToken("")).toEqual({ name: null, stepNum: null });
  });
});
