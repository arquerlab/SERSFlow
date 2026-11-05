import { describe, expect, it } from "vitest";
import { guessSubshell, isLowJComponentId, SUBSHELL_AREA_RATIO } from "./spinOrbit";

describe("F3 spin-orbit helpers", () => {
  it("uses the 2j+1 area ratios", () => {
    expect(SUBSHELL_AREA_RATIO.p).toBe(0.5);
    expect(SUBSHELL_AREA_RATIO.d).toBeCloseTo(2 / 3);
    expect(SUBSHELL_AREA_RATIO.f).toBe(0.75);
  });

  it("guesses the subshell from a peak name or region", () => {
    expect(guessSubshell("peak_1", "Co_2p3/2")).toBe("p");
    expect(guessSubshell("4f7_2")).toBe("f");
    expect(guessSubshell("Ag 3d")).toBe("d");
    expect(guessSubshell("O_1s", "")).toBeNull();
  });

  it("recognises low-j members so they get no partner button", () => {
    expect(isLowJComponentId("2p1_2")).toBe(true);
    expect(isLowJComponentId("peak_1_2p1_2")).toBe(true);
    expect(isLowJComponentId("4f5/2")).toBe(true);
    expect(isLowJComponentId("2p3_2")).toBe(false);
    expect(isLowJComponentId("peak_1")).toBe(false);
  });
});
