import { describe, expect, it } from "vitest";
import {
  componentUncertaintyCells,
  decimalsForError,
  formatInterval,
  formatValueError,
  hasAnyStderr,
  mcToCovRatio,
  type MonteCarloRow,
} from "./fitUncertainty";

describe("F2 uncertainty formatting", () => {
  it("rounds the value to the error's two significant digits", () => {
    expect(decimalsForError(0.0123)).toBe(3);
    expect(decimalsForError(12.3)).toBe(0);
    expect(formatValueError(779.40123, 0.0123)).toBe("779.401 ± 0.012");
    expect(formatValueError(6938.67, 16.54)).toBe("6939 ± 17");
    expect(formatValueError(2.2, null)).toBe("2.200");
    expect(formatValueError(null, 1)).toBe("—");
    expect(formatInterval(2.1, 2.3, 0.05)).toBe("[2.100, 2.300]");
  });

  it("marks fixed parameters and appends area and %area", () => {
    const cells = componentUncertaintyCells({
      component_id: "a",
      component_type: "gl",
      param_keys: ["pos", "m"],
      params: { pos: 780.0, m: 30 },
      stderr: { pos: 0.002, m: null },
      area: 6938.7,
      area_stderr: 16.5,
      area_pct: 76.25,
      area_pct_stderr: 0.13,
    });
    expect(cells.map((c) => c.key)).toEqual(["pos", "m", "area", "%area"]);
    expect(cells[1].fixed).toBe(true);
    expect(cells[1].text).toContain("(fixed)");
    expect(cells[3].text).toBe("76.25 ± 0.13");
  });

  it("detects runs without stored errors and computes the MC/cov ratio", () => {
    expect(hasAnyStderr([{ component_id: "a", component_type: "gl", stderr: { pos: null } }])).toBe(false);
    expect(hasAnyStderr([{ component_id: "a", component_type: "gl", area_pct_stderr: 0.1 }])).toBe(true);
    const r = { mc_sd: 0.3, stderr_cov: 0.1 } as MonteCarloRow;
    expect(mcToCovRatio(r)).toBeCloseTo(3);
    expect(mcToCovRatio({ ...r, stderr_cov: null })).toBeNull();
  });
});
