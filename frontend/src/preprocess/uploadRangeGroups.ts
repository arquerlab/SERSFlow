/** Coarse wavenumber bucketing (cm⁻¹): lower edge rounded down, upper rounded up. */

export const WN_BUCKET_STEP_CM1 = 100;

function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Bucket edges after rounding (same key => grouped together). */
export function bucketWnRange(wnMin: number, wnMax: number): { lo: number; hi: number; key: string } {
  const s = WN_BUCKET_STEP_CM1;
  const lo = Math.floor(wnMin / s) * s;
  const hi = Math.ceil(wnMax / s) * s;
  return { lo, hi, key: `${lo}|${hi}` };
}

export type UploadRow = {
  relative_path: string;
  wn_min?: number | null;
  wn_max?: number | null;
  spectrum_count?: number | null;
};

export type RangeGroupOption = {
  key: string;
  label: string;
  paths: string[];
  spectrumCount: number;
};

/**
 * Group uploads by rounded wavenumber span. Files without range go under "Unknown range".
 */
export function buildRangeGroupOptions(items: UploadRow[]): RangeGroupOption[] {
  const buckets = new Map<string, { paths: string[]; spectrumCount: number; lo: number; hi: number }>();

  for (const it of items) {
    const wmin = num(it.wn_min);
    const wmax = num(it.wn_max);
    const nSpec = Math.max(1, Math.trunc(num(it.spectrum_count) ?? 1));

    if (wmin == null || wmax == null) {
      const k = "__unknown__";
      const cur = buckets.get(k);
      if (cur) {
        cur.paths.push(it.relative_path);
        cur.spectrumCount += nSpec;
      } else {
        buckets.set(k, {
          paths: [it.relative_path],
          spectrumCount: nSpec,
          lo: NaN,
          hi: NaN,
        });
      }
      continue;
    }

    const { lo, hi, key } = bucketWnRange(wmin, wmax);
    const cur = buckets.get(key);
    if (cur) {
      cur.paths.push(it.relative_path);
      cur.spectrumCount += nSpec;
    } else {
      buckets.set(key, { paths: [it.relative_path], spectrumCount: nSpec, lo, hi });
    }
  }

  const out: RangeGroupOption[] = [];
  for (const [key, v] of buckets) {
    if (key === "__unknown__") {
      out.push({
        key,
        label: `Unknown range (${v.paths.length} file(s), ${v.spectrumCount} spectra)`,
        paths: v.paths,
        spectrumCount: v.spectrumCount,
      });
    } else {
      out.push({
        key,
        label: `${v.lo}–${v.hi} cm⁻¹ (${v.paths.length} file(s), ${v.spectrumCount} spectra)`,
        paths: v.paths,
        spectrumCount: v.spectrumCount,
      });
    }
  }

  out.sort((a, b) => {
    if (a.key === "__unknown__") return 1;
    if (b.key === "__unknown__") return -1;
    const al = Number(a.key.split("|")[0]);
    const bl = Number(b.key.split("|")[0]);
    return al - bl;
  });

  return out;
}
