import Plotly from "plotly.js-dist-min";
import { zipSync, strToU8 } from "fflate";

export type CsvRow = Record<string, string | number | boolean | null | undefined>;

export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadText(filename: string, text: string, mime = "text/plain;charset=utf-8") {
  downloadBlob(filename, new Blob([text], { type: mime }));
}

function csvEscapeCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export function rowsToCsv(rows: CsvRow[], headers?: string[]): string {
  const outRows = rows ?? [];
  const keys =
    headers && headers.length
      ? headers
      : Array.from(
          outRows.reduce((acc, r) => {
            for (const k of Object.keys(r ?? {})) acc.add(k);
            return acc;
          }, new Set<string>())
        );
  const lines: string[] = [];
  lines.push(keys.map(csvEscapeCell).join(","));
  for (const r of outRows) {
    lines.push(keys.map((k) => csvEscapeCell((r ?? {})[k])).join(","));
  }
  return lines.join("\r\n");
}

export function downloadCsv(filename: string, rows: CsvRow[], headers?: string[]) {
  const text = rowsToCsv(rows, headers);
  downloadText(filename, text, "text/csv;charset=utf-8");
}

function dataUrlToBytes(dataUrl: string): Uint8Array {
  const idx = dataUrl.indexOf(",");
  const b64 = idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl;
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

export async function plotlyDivToPngBytes(
  plotDiv: HTMLElement,
  opts?: { width?: number; height?: number; scale?: number; background?: string }
): Promise<Uint8Array> {
  const dataUrl = (await Plotly.toImage(plotDiv as any, {
    format: "png",
    width: opts?.width ?? 1200,
    height: opts?.height,
    scale: opts?.scale ?? 2,
    // Plotly uses `bgcolor` internally for layout; `toImage` supports `setBackground`.
    setBackground: opts?.background ?? "white",
  })) as string;
  return dataUrlToBytes(dataUrl);
}

export type ZipInput = { path: string; bytes: Uint8Array | string };

export function zipFiles(inputs: ZipInput[]): Blob {
  const fileMap: Record<string, Uint8Array> = {};
  for (const f of inputs) {
    if (!f?.path) continue;
    fileMap[f.path] = typeof f.bytes === "string" ? strToU8(f.bytes) : f.bytes;
  }
  const zipped = zipSync(fileMap, { level: 6 });
  return new Blob([zipped as unknown as BlobPart], { type: "application/zip" });
}

