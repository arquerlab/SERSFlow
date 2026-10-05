import { describe, expect, it } from "vitest";
import {
  ALL_VALENCE_BANDS_REGION,
  regionSubsetDisplayName,
  shortXpsRegionLabel,
  spectrumRegionMatchesPicks,
} from "./fittingUtils";

describe("shortXpsRegionLabel", () => {
  it("keeps core-level names as-is", () => {
    expect(shortXpsRegionLabel("C1s")).toBe("C1s");
    expect(shortXpsRegionLabel("O1s")).toBe("O1s");
  });

  it("maps all valence bands to vb-all", () => {
    expect(shortXpsRegionLabel(ALL_VALENCE_BANDS_REGION)).toBe("vb-all");
  });

  it("shortens specific valence-band regions", () => {
    expect(shortXpsRegionLabel("vb-O1s")).toBe("vb-O1s");
    expect(shortXpsRegionLabel("VB")).toBe("vb");
    expect(shortXpsRegionLabel("valence band")).toBe("vb");
    expect(shortXpsRegionLabel("Fermi edge")).toBe("vb");
  });
});

describe("regionSubsetDisplayName", () => {
  it("joins short labels without counts or prefixes", () => {
    expect(regionSubsetDisplayName(["C1s"])).toBe("C1s");
    expect(regionSubsetDisplayName([ALL_VALENCE_BANDS_REGION])).toBe("vb-all");
    expect(regionSubsetDisplayName(["C1s", "vb-O1s"])).toBe("C1s+vb-O1s");
    expect(regionSubsetDisplayName(["O1s", ALL_VALENCE_BANDS_REGION])).toBe("O1s+vb-all");
  });
});

describe("spectrumRegionMatchesPicks", () => {
  it("matches exact regions and all valence bands", () => {
    expect(spectrumRegionMatchesPicks("C1s", ["C1s"])).toBe(true);
    expect(spectrumRegionMatchesPicks("O1s", ["C1s"])).toBe(false);
    expect(spectrumRegionMatchesPicks("vb-O1s", [ALL_VALENCE_BANDS_REGION])).toBe(true);
    expect(spectrumRegionMatchesPicks("valence band", [ALL_VALENCE_BANDS_REGION])).toBe(true);
    expect(spectrumRegionMatchesPicks("C1s", [ALL_VALENCE_BANDS_REGION])).toBe(false);
  });
});
