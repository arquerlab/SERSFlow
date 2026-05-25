export function summarizeUploadLabels(labels?: Record<string, unknown> | null): {
  short: string;
  full: string;
} {
  if (!labels || typeof labels !== "object") return { short: "", full: "" };
  const parts: string[] = [];

  const num = (v: unknown) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };

  if (labels.sample) parts.push(String(labels.sample));
  if (labels.ph != null && labels.ph !== "") parts.push(`pH=${labels.ph}`);
  if (labels.gas) parts.push(String(labels.gas));

  const pv = num(labels.potential_V);
  const pref = labels.potential_ref;
  if (pv != null && pref) {
    if (pref === "OCP") parts.push("OCP");
    else if (pref === "VRHE") parts.push(`${pv}VRHE`);
    else if (pref === "VAgAgCl") parts.push(`${pv}V Ag/AgCl`);
    else if (pref === "V") parts.push(`${pv} V`);
    else parts.push(`${pv}V`);
  }

  const cd = num(labels.current_density_A_cm2);
  const caLegacy = num(labels.current_A);
  const cAmp = cd != null ? cd : caLegacy;
  if (cAmp != null) {
    const macm2 = cAmp * 1000;
    parts.push(`${Number.isFinite(macm2) ? macm2 : cAmp}mA·cm⁻²`);
  }

  const lnm = num(labels.laser_nm);
  if (lnm != null) parts.push(`${lnm}nm`);
  const lp = num(labels.laser_power_pct);
  if (lp != null) parts.push(`${lp}%`);

  if (labels.electrolyte) {
    const cM = num(
      labels.concentration_M != null ? labels.concentration_M : labels.electrolyte_M
    );
    if (cM != null) parts.push(`${cM}M ${labels.electrolyte}`);
    else parts.push(String(labels.electrolyte));
  }

  const full = parts.join(" • ");
  const maxPrimary = 5;
  const short =
    parts.length <= maxPrimary ? full : `${parts.slice(0, maxPrimary).join(" • ")} • …`;
  return { short, full };
}

export function formatFileSizeMb(bytes: number): string {
  const mb = (Number(bytes) || 0) / (1024 * 1024);
  if (!Number.isFinite(mb) || mb <= 0) return "0.000 MB";
  return `${mb.toFixed(3)} MB`;
}
