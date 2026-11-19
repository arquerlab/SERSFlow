import { describe, expect, it } from "vitest";
import {
  buildVolume,
  depthProfile,
  montageFigure,
  nearestIdx,
  pickLayers,
  project,
  roiSpectrumIds,
  sliceXY,
  sliceXZ,
  sliceYZ,
  stackFigure,
  volumeCsvRows,
  zIndicesInRange,
  type VolumeRow,
} from "./volumeModel";

// 3 x 2 x 4 volume, value = 100*z_index + 10*y + x, z = -10, -5, 0, 5
function rows(): VolumeRow[] {
  const out: VolumeRow[] = [];
  for (let zi = 0; zi < 4; zi++)
    for (let y = 0; y < 2; y++)
      for (let x = 0; x < 3; x++)
        out.push({ spectrum_id: `s${zi}_${y}_${x}`, x, y, z: zi * 5 - 10, a: 100 * zi + 10 * y + x, b: 2 });
  return out;
}

describe("buildVolume and slices", () => {
  const v = buildVolume(rows());
  it("indexes the grid", () => {
    expect(v.xs).toEqual([0, 1, 2]);
    expect(v.ys).toEqual([0, 1]);
    expect(v.zs).toEqual([-10, -5, 0, 5]);
    expect(v.values[2][1][2]).toBe(212);
    expect(v.vmin).toBe(0);
    expect(v.vmax).toBe(312);
  });
  it("slices XY, XZ, YZ", () => {
    expect(sliceXY(v, 1)).toEqual([[100, 101, 102], [110, 111, 112]]);
    expect(sliceXZ(v, 1)[3]).toEqual([310, 311, 312]);
    expect(sliceYZ(v, 2).map((r) => r[1])).toEqual([12, 112, 212, 312]);
  });
  it("applies depth calibration", () => {
    const c = buildVolume(rows(), { zOffset: -10, zScale: 2 });
    expect(c.zs).toEqual([0, 10, 20, 30]);
  });
  it("ratio and mask", () => {
    const r = buildVolume(rows(), { ratio: true });
    expect(r.values[1][0][0]).toBe(50);
    const m = buildVolume(rows(), { maskMin: 100 });
    expect(m.values[0][0][0]).toBeNull();
    expect(m.values[1][0][0]).toBe(100);
  });
  it("ratio with zero or missing denominator is null", () => {
    const rs = rows();
    rs[0].b = 0;
    rs[1].b = null;
    const r = buildVolume(rs, { ratio: true });
    expect(r.values[0][0][0]).toBeNull();
    expect(r.values[0][0][1]).toBeNull();
  });
});

describe("projections", () => {
  const v = buildVolume(rows());
  const all = [0, 1, 2, 3];
  it("mean / max / min / sum", () => {
    expect(project(v, "mean", all)[0][0]).toBe(150);
    expect(project(v, "max", all)[0][0]).toBe(300);
    expect(project(v, "min", all)[0][0]).toBe(0);
    expect(project(v, "sum", all)[0][0]).toBe(600);
  });
  it("slab restricts depth range", () => {
    const slab = zIndicesInRange(v, -5, 0);
    expect(slab).toEqual([1, 2]);
    expect(project(v, "mean", slab)[0][0]).toBe(150);
  });
  it("argmax returns calibrated depth of peak", () => {
    const rs = rows();
    rs.find((r) => r.spectrum_id === "s1_0_0")!.a = 9999;
    const vv = buildVolume(rs);
    expect(project(vv, "argmax", all)[0][0]).toBe(-5);
    expect(project(vv, "argmax", all)[1][1]).toBe(5);
  });
});

describe("depth profile and ROI", () => {
  const v = buildVolume(rows());
  it("single point", () => {
    const p = depthProfile(v, 1, 0, 0);
    expect(p.mean).toEqual([1, 101, 201, 301]);
    expect(p.std).toEqual([0, 0, 0, 0]);
  });
  it("radius averages the neighbourhood", () => {
    const p = depthProfile(v, 1, 0, 1); // 3 x 2 cells = whole plane
    expect(p.n).toEqual([6, 6, 6, 6]);
    expect(p.mean[0]).toBeCloseTo(6, 6);
    expect((p.std[0] as number) > 0).toBe(true);
  });
  it("roi ids at depth", () => {
    expect(roiSpectrumIds(v, 2, 0, 0, 0)).toEqual(["s2_0_0"]);
    expect(roiSpectrumIds(v, 2, 0, 0, 1).sort()).toEqual(["s2_0_0", "s2_0_1", "s2_1_0", "s2_1_1"]);
  });
});

describe("helpers and figures", () => {
  const v = buildVolume(rows());
  it("pickLayers includes endpoints and respects the cap", () => {
    expect(pickLayers(60, 12)).toHaveLength(12);
    expect(pickLayers(60, 12)[0]).toBe(0);
    expect(pickLayers(60, 12).at(-1)).toBe(59);
    expect(pickLayers(3, 12)).toEqual([0, 1, 2]);
  });
  it("nearestIdx", () => {
    expect(nearestIdx([0, 5, 10], 6)).toBe(1);
  });
  it("stack figure: one flat surface per layer at its own z", () => {
    const fig = stackFigure(v, [0, 3], { opacity: 0.8, label: "A", title: "t" });
    expect(fig.data).toHaveLength(2);
    expect(fig.data[0].type).toBe("surface");
    expect(new Set(fig.data[0].z.flat())).toEqual(new Set([-10]));
    expect(new Set(fig.data[1].z.flat())).toEqual(new Set([5]));
    expect(fig.data[0].cmin).toBe(0);
    expect(fig.data[0].cmax).toBe(312);
    expect(fig.data[1].showscale).toBe(false);
  });
  it("montage uses a shared colour range and one subplot per layer", () => {
    const fig = montageFigure(v, [0, 1, 2], { cols: 2, shared: true, label: "A", title: "t" });
    expect(fig.data).toHaveLength(3);
    expect(fig.data.every((d) => d.zmin === 0 && d.zmax === 312)).toBe(true);
    expect(fig.layout.xaxis3.domain).toBeDefined();
  });
  it("csv rows cover every voxel", () => {
    expect(volumeCsvRows(v, "A")).toHaveLength(24);
  });
});
