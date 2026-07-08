import { describe, expect, it, vi } from "vitest";
import { clampSplitWidth, readSplitWidth, writeSplitWidth } from "../components/splitWidth";

describe("splitWidth", () => {
  it("clamps values to min/max", () => {
    expect(clampSplitWidth(100, 280, 720)).toBe(280);
    expect(clampSplitWidth(900, 280, 720)).toBe(720);
    expect(clampSplitWidth(400, 280, 720)).toBe(400);
  });

  it("reads and writes localStorage", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => store.set(k, v),
      removeItem: (k: string) => store.delete(k),
    });
    writeSplitWidth("test-split-w", 420);
    expect(readSplitWidth("test-split-w", 300, 280, 720)).toBe(420);
    vi.unstubAllGlobals();
  });
});
