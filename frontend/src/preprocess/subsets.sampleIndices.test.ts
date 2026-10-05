import { describe, expect, it } from "vitest";
import { sampleIndices } from "./subsets";

describe("sampleIndices", () => {
  it("returns a deterministic sample for a seed", () => {
    const pool = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
    expect(sampleIndices(pool, 4, 42)).toEqual(sampleIndices(pool, 4, 42));
  });

  it("varies with seed so repeated region creates differ", () => {
    const pool = Array.from({ length: 56 }, (_, i) => i);
    const a = sampleIndices(pool, 4, 100);
    const b = sampleIndices(pool, 4, 101);
    expect(a).toHaveLength(4);
    expect(b).toHaveLength(4);
    expect(a.join(",")).not.toBe(b.join(","));
  });

  it("returns the full pool when n >= length", () => {
    expect(sampleIndices([1, 3, 5], 10, 1).sort()).toEqual([1, 3, 5]);
  });
});
