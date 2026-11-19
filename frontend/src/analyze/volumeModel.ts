/**
 * Volume-map (X x Y x Z grid) model and figure builders for the Analyze tab.
 *
 * Pure functions only (no React / Plotly import) so they are unit-testable.
 * Layout convention: values[zi][yi][xi], zs sorted ascending (after depth calibration).
 */

export type PlotlyFig = { data: any[]; layout: Record<string, any> };

export type VolumeRow = {
  spectrum_id: string;
  x: number;
  y: number;
  z: number;
  /** Primary feature value. */
  a: number | null;
  /** Optional second feature (for ratio maps). */
  b: number | null;
};

export type VolumeOptions = {
  /** Show a / b instead of a. */
  ratio?: boolean;
  /** Drop voxels whose primary value `a` is below this (signal threshold). */
  maskMin?: number | null;
  /** Drop voxels whose primary value `a` is above this. */
  maskMax?: number | null;
  /** Depth calibration: z' = (z - zOffset) * zScale (zScale > 0; e.g. refractive-index factor). */
  zOffset?: number;
  zScale?: number;
};

export type Volume = {
  xs: number[];
  ys: number[];
  zs: number[];
  values: (number | null)[][][];
  ids: (string | null)[][][];
  /** Finite min / max over the whole volume (shared colour scale). */
  vmin: number;
  vmax: number;
};

export type ProjectionMode = "mean" | "max" | "min" | "sum" | "argmax";

const KEY_DECIMALS = 6;

function key(v: number): string {
  return v.toFixed(KEY_DECIMALS);
}

function uniqueSorted(vals: number[]): number[] {
  const seen = new Map<string, number>();
  for (const v of vals) if (Number.isFinite(v) && !seen.has(key(v))) seen.set(key(v), v);
  return Array.from(seen.values()).sort((p, q) => p - q);
}

export function calibrateZ(z: number, opts: VolumeOptions): number {
  const scale = opts.zScale !== undefined && Number.isFinite(opts.zScale) && opts.zScale > 0 ? opts.zScale : 1;
  const off = opts.zOffset !== undefined && Number.isFinite(opts.zOffset) ? opts.zOffset : 0;
  return (z - off) * scale;
}

export function voxelValue(row: VolumeRow, opts: VolumeOptions): number | null {
  const a = row.a;
  if (a === null || !Number.isFinite(a)) return null;
  if (opts.maskMin !== undefined && opts.maskMin !== null && Number.isFinite(opts.maskMin) && a < opts.maskMin) return null;
  if (opts.maskMax !== undefined && opts.maskMax !== null && Number.isFinite(opts.maskMax) && a > opts.maskMax) return null;
  if (!opts.ratio) return a;
  const b = row.b;
  if (b === null || !Number.isFinite(b) || b === 0) return null;
  return a / b;
}

export function buildVolume(rows: VolumeRow[], opts: VolumeOptions = {}): Volume {
  const xsRaw = uniqueSorted(rows.map((r) => r.x));
  const ysRaw = uniqueSorted(rows.map((r) => r.y));
  const zsRaw = uniqueSorted(rows.map((r) => r.z));
  const xi = new Map(xsRaw.map((v, i) => [key(v), i]));
  const yi = new Map(ysRaw.map((v, i) => [key(v), i]));
  const zi = new Map(zsRaw.map((v, i) => [key(v), i]));
  const values: (number | null)[][][] = zsRaw.map(() => ysRaw.map(() => xsRaw.map(() => null)));
  const ids: (string | null)[][][] = zsRaw.map(() => ysRaw.map(() => xsRaw.map(() => null)));
  let vmin = Infinity;
  let vmax = -Infinity;
  for (const r of rows) {
    const ix = xi.get(key(r.x));
    const iy = yi.get(key(r.y));
    const iz = zi.get(key(r.z));
    if (ix === undefined || iy === undefined || iz === undefined) continue;
    ids[iz][iy][ix] = r.spectrum_id;
    const v = voxelValue(r, opts);
    values[iz][iy][ix] = v;
    if (v !== null) {
      if (v < vmin) vmin = v;
      if (v > vmax) vmax = v;
    }
  }
  if (!Number.isFinite(vmin)) {
    vmin = 0;
    vmax = 1;
  }
  return { xs: xsRaw, ys: ysRaw, zs: zsRaw.map((z) => calibrateZ(z, opts)), values, ids, vmin, vmax };
}

export function isVolume(v: Volume): boolean {
  return v.zs.length > 1 && v.xs.length > 0 && v.ys.length > 0;
}

/** XY plane at depth index zi -> [yi][xi]. */
export function sliceXY(v: Volume, zi: number): (number | null)[][] {
  return v.values[clampIdx(zi, v.zs.length)];
}

/** XZ plane at row yi -> [zi][xi]. */
export function sliceXZ(v: Volume, yi: number): (number | null)[][] {
  const y = clampIdx(yi, v.ys.length);
  return v.zs.map((_, z) => v.values[z][y]);
}

/** YZ plane at column xi -> [zi][yi]. */
export function sliceYZ(v: Volume, xi: number): (number | null)[][] {
  const x = clampIdx(xi, v.xs.length);
  return v.zs.map((_, z) => v.ys.map((__, y) => v.values[z][y][x]));
}

export function clampIdx(i: number, n: number): number {
  if (!Number.isFinite(i)) return 0;
  return Math.min(Math.max(Math.round(i), 0), Math.max(0, n - 1));
}

export function nearestIdx(arr: number[], value: number): number {
  let best = 0;
  let bd = Infinity;
  for (let i = 0; i < arr.length; i++) {
    const d = Math.abs(arr[i] - value);
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return best;
}

/** Depth indices (inclusive) whose z lies in [z0, z1]. */
export function zIndicesInRange(v: Volume, z0: number, z1: number): number[] {
  const lo = Math.min(z0, z1);
  const hi = Math.max(z0, z1);
  const out: number[] = [];
  v.zs.forEach((z, i) => {
    if (z >= lo - 1e-9 && z <= hi + 1e-9) out.push(i);
  });
  return out;
}

/**
 * Collapse depth over `zIdx` -> [yi][xi]. `argmax` returns the depth (calibrated z, not index) at which
 * each XY column peaks. Columns with no finite value stay null.
 */
export function project(v: Volume, mode: ProjectionMode, zIdx: number[]): (number | null)[][] {
  return v.ys.map((_, y) =>
    v.xs.map((__, x) => {
      let sum = 0;
      let n = 0;
      let best: number | null = null;
      let bestZ: number | null = null;
      let worst: number | null = null;
      for (const z of zIdx) {
        const val = v.values[z]?.[y]?.[x];
        if (val === null || val === undefined || !Number.isFinite(val)) continue;
        sum += val;
        n += 1;
        if (best === null || val > best) {
          best = val;
          bestZ = v.zs[z];
        }
        if (worst === null || val < worst) worst = val;
      }
      if (n === 0) return null;
      if (mode === "mean") return sum / n;
      if (mode === "sum") return sum;
      if (mode === "max") return best;
      if (mode === "min") return worst;
      return bestZ;
    })
  );
}

/** Cells within Chebyshev `radius` of (xi, yi). */
export function roiCells(v: Volume, xi: number, yi: number, radius: number): Array<[number, number]> {
  const r = Math.max(0, Math.floor(radius));
  const cx = clampIdx(xi, v.xs.length);
  const cy = clampIdx(yi, v.ys.length);
  const out: Array<[number, number]> = [];
  for (let y = Math.max(0, cy - r); y <= Math.min(v.ys.length - 1, cy + r); y++) {
    for (let x = Math.max(0, cx - r); x <= Math.min(v.xs.length - 1, cx + r); x++) out.push([x, y]);
  }
  return out;
}

export type DepthProfile = { z: number[]; mean: (number | null)[]; std: (number | null)[]; n: number[] };

/** Feature vs depth over an XY region (mean +/- std of the finite voxels at each depth). */
export function depthProfile(v: Volume, xi: number, yi: number, radius: number): DepthProfile {
  const cells = roiCells(v, xi, yi, radius);
  const mean: (number | null)[] = [];
  const std: (number | null)[] = [];
  const n: number[] = [];
  for (let z = 0; z < v.zs.length; z++) {
    const vals: number[] = [];
    for (const [x, y] of cells) {
      const val = v.values[z][y][x];
      if (val !== null && Number.isFinite(val)) vals.push(val);
    }
    n.push(vals.length);
    if (!vals.length) {
      mean.push(null);
      std.push(null);
      continue;
    }
    const m = vals.reduce((s, q) => s + q, 0) / vals.length;
    mean.push(m);
    std.push(vals.length > 1 ? Math.sqrt(vals.reduce((s, q) => s + (q - m) ** 2, 0) / (vals.length - 1)) : 0);
  }
  return { z: v.zs.slice(), mean, std, n };
}

/** Spectrum ids of the ROI at depth index zi. */
export function roiSpectrumIds(v: Volume, zi: number, xi: number, yi: number, radius: number): string[] {
  const z = clampIdx(zi, v.zs.length);
  const out: string[] = [];
  for (const [x, y] of roiCells(v, xi, yi, radius)) {
    const id = v.ids[z][y][x];
    if (id) out.push(id);
  }
  return out;
}

/** Evenly spaced depth indices, at most `max` of them, always including first and last. */
export function pickLayers(nz: number, max: number): number[] {
  if (nz <= 0) return [];
  const m = Math.max(1, Math.floor(max));
  if (nz <= m) return Array.from({ length: nz }, (_, i) => i);
  if (m === 1) return [0];
  const out = new Set<number>();
  for (let i = 0; i < m; i++) out.add(Math.round((i * (nz - 1)) / (m - 1)));
  return Array.from(out).sort((a, b) => a - b);
}

export type ColorRange = { zmin: number; zmax: number };

export function colorRange(v: Volume, shared: boolean, plane?: (number | null)[][]): ColorRange {
  if (shared || !plane) return { zmin: v.vmin, zmax: v.vmax };
  let lo = Infinity;
  let hi = -Infinity;
  for (const row of plane)
    for (const val of row)
      if (val !== null && Number.isFinite(val)) {
        if (val < lo) lo = val;
        if (val > hi) hi = val;
      }
  return Number.isFinite(lo) ? { zmin: lo, zmax: hi } : { zmin: v.vmin, zmax: v.vmax };
}

const MARGIN = { l: 60, r: 20, t: 40, b: 50 };

export const Z_TITLE = "Depth z (µm)";

export function planeFigure(args: {
  title: string;
  x: number[];
  y: number[];
  z: (number | null)[][];
  xTitle: string;
  yTitle: string;
  colorbarTitle: string;
  range: ColorRange;
  crosshair?: { x: number; y: number } | null;
  colorscale?: string;
}): PlotlyFig {
  const { crosshair } = args;
  const shapes: any[] = [];
  if (crosshair) {
    const line = { color: "rgba(255,255,255,0.9)", width: 1, dash: "dot" };
    shapes.push({ type: "line", xref: "x", yref: "paper", x0: crosshair.x, x1: crosshair.x, y0: 0, y1: 1, line });
    shapes.push({ type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: crosshair.y, y1: crosshair.y, line });
  }
  return {
    data: [
      {
        type: "heatmap",
        x: args.x,
        y: args.y,
        z: args.z,
        colorscale: args.colorscale ?? "Viridis",
        zmin: args.range.zmin,
        zmax: args.range.zmax,
        colorbar: { title: { text: args.colorbarTitle } },
        hovertemplate: `${args.xTitle}: %{x}<br>${args.yTitle}: %{y}<br>${args.colorbarTitle}: %{z}<extra></extra>`,
      },
    ],
    layout: {
      title: { text: args.title },
      xaxis: { title: { text: args.xTitle } },
      yaxis: { title: { text: args.yTitle } },
      shapes,
      margin: MARGIN,
    },
  };
}

export function profileFigure(p: DepthProfile, label: string, title: string): PlotlyFig {
  const upper = p.mean.map((m, i) => (m === null ? null : m + (p.std[i] ?? 0)));
  const lower = p.mean.map((m, i) => (m === null ? null : m - (p.std[i] ?? 0)));
  const hasBand = p.n.some((n) => n > 1);
  const data: any[] = [];
  if (hasBand) {
    data.push({ type: "scatter", mode: "lines", x: p.z, y: upper, line: { width: 0 }, hoverinfo: "skip", showlegend: false });
    data.push({
      type: "scatter",
      mode: "lines",
      x: p.z,
      y: lower,
      line: { width: 0 },
      fill: "tonexty",
      fillcolor: "rgba(100,140,220,0.25)",
      hoverinfo: "skip",
      name: "±1 std (ROI)",
    });
  }
  data.push({
    type: "scatter",
    mode: "lines+markers",
    x: p.z,
    y: p.mean,
    name: label,
    line: { color: "#2a6fdb", width: 2 },
    marker: { size: 5 },
    hovertemplate: `z=%{x} µm<br>${label}=%{y}<extra></extra>`,
  });
  return {
    data,
    layout: {
      title: { text: title },
      xaxis: { title: { text: Z_TITLE } },
      yaxis: { title: { text: label } },
      margin: MARGIN,
      showlegend: hasBand,
    },
  };
}

/** Small multiples of depth layers on one shared (or per-plane) colour scale. */
export function montageFigure(v: Volume, zIdx: number[], opts: { cols: number; shared: boolean; label: string; title: string }): PlotlyFig {
  const cols = Math.max(1, Math.floor(opts.cols));
  const rows = Math.max(1, Math.ceil(zIdx.length / cols));
  const gapX = 0.03;
  const gapY = 0.07;
  const w = (1 - gapX * (cols - 1)) / cols;
  const h = (1 - gapY * (rows - 1)) / rows;
  const data: any[] = [];
  const layout: Record<string, any> = { title: { text: opts.title }, margin: { l: 40, r: 20, t: 50, b: 30 }, annotations: [] };
  const range = colorRange(v, true);
  zIdx.forEach((zi, k) => {
    const r = Math.floor(k / cols);
    const c = k % cols;
    const n = k + 1;
    const x0 = c * (w + gapX);
    const y1 = 1 - r * (h + gapY);
    const plane = sliceXY(v, zi);
    const rg = opts.shared ? range : colorRange(v, false, plane);
    data.push({
      type: "heatmap",
      x: v.xs,
      y: v.ys,
      z: plane,
      xaxis: n === 1 ? "x" : `x${n}`,
      yaxis: n === 1 ? "y" : `y${n}`,
      colorscale: "Viridis",
      zmin: rg.zmin,
      zmax: rg.zmax,
      showscale: opts.shared && k === 0,
      colorbar: opts.shared && k === 0 ? { title: { text: opts.label }, len: 0.8 } : undefined,
      hovertemplate: `x: %{x}<br>y: %{y}<br>${opts.label}: %{z}<extra>z=${v.zs[zi].toFixed(1)} µm</extra>`,
    });
    layout[n === 1 ? "xaxis" : `xaxis${n}`] = { domain: [x0, x0 + w], anchor: n === 1 ? "y" : `y${n}`, showticklabels: r === rows - 1 || k + cols >= zIdx.length };
    layout[n === 1 ? "yaxis" : `yaxis${n}`] = { domain: [y1 - h, y1], anchor: n === 1 ? "x" : `x${n}`, showticklabels: c === 0 };
    layout.annotations.push({
      text: `z=${v.zs[zi].toFixed(1)}`,
      xref: "paper",
      yref: "paper",
      x: x0 + w / 2,
      y: y1,
      showarrow: false,
      yanchor: "bottom",
      font: { size: 10 },
    });
  });
  return { data, layout };
}

/**
 * Stack of heatmaps in 3-D: each chosen depth layer is a flat, flat-shaded colour plane at its own z, so the
 * layer a value belongs to is read from the vertical position (no point cloud ambiguity).
 */
export function stackFigure(
  v: Volume,
  zIdx: number[],
  opts: { opacity: number; label: string; title: string; reverseZ?: boolean; zSpread?: number }
): PlotlyFig {
  const range = colorRange(v, true);
  const nx = v.xs.length;
  const ny = v.ys.length;
  const data = zIdx.map((zi, k) => {
    const zPlane = v.ys.map(() => v.xs.map(() => v.zs[zi]));
    return {
      type: "surface",
      x: v.xs,
      y: v.ys,
      z: zPlane,
      surfacecolor: sliceXY(v, zi),
      cmin: range.zmin,
      cmax: range.zmax,
      colorscale: "Viridis",
      opacity: Math.min(1, Math.max(0.05, opts.opacity)),
      showscale: k === 0,
      colorbar: k === 0 ? { title: { text: opts.label }, len: 0.7 } : undefined,
      lighting: { ambient: 1, diffuse: 0, specular: 0, roughness: 1, fresnel: 0 },
      contours: { x: { show: false }, y: { show: false }, z: { show: false } },
      hovertemplate: `x: %{x}<br>y: %{y}<br>z=${v.zs[zi].toFixed(1)} µm<br>${opts.label}: %{surfacecolor}<extra></extra>`,
      name: `z=${v.zs[zi].toFixed(1)}`,
    };
  });
  const span = Math.max(1e-9, Math.max(...v.xs) - Math.min(...v.xs), Math.max(...v.ys) - Math.min(...v.ys));
  const zRange = Math.max(1e-9, Math.max(...v.zs) - Math.min(...v.zs));
  const zAspect = Math.min(1.6, Math.max(0.4, ((opts.zSpread ?? 1) * zRange) / span));
  return {
    data,
    layout: {
      title: { text: opts.title },
      margin: { l: 0, r: 0, t: 40, b: 0 },
      scene: {
        xaxis: { title: { text: "x (µm)" }, nticks: Math.min(nx, 8) },
        yaxis: { title: { text: "y (µm)" }, nticks: Math.min(ny, 8) },
        zaxis: { title: { text: Z_TITLE }, autorange: opts.reverseZ ? "reversed" : true },
        aspectmode: "manual",
        aspectratio: { x: 1, y: 1, z: zAspect },
        camera: { eye: { x: 1.6, y: -1.6, z: 0.9 } },
      },
    },
  };
}

export function volumeCsvRows(v: Volume, label: string): Array<Record<string, string | number | null>> {
  const out: Array<Record<string, string | number | null>> = [];
  for (let z = 0; z < v.zs.length; z++)
    for (let y = 0; y < v.ys.length; y++)
      for (let x = 0; x < v.xs.length; x++)
        out.push({
          spectrum_id: v.ids[z][y][x],
          x_um: v.xs[x],
          y_um: v.ys[y],
          z_um: v.zs[z],
          [label]: v.values[z][y][x],
        });
  return out;
}
