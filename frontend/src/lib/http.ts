/**
 * Shared fetch helpers for preprocess and analyze API clients.
 */

export function formatErrorDetail(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return JSON.stringify(detail);
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return `Request failed (${status})`;
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { cache: "no-store", credentials: "include", ...init });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!res.ok) {
        throw new Error(text.trim() || formatErrorDetail(null, res.status));
      }
      throw new Error(`Expected JSON response from ${url}, received non-JSON body`);
    }
  }
  if (!res.ok) {
    const detail =
      (data && typeof data === "object" && "detail" in data ? (data as { detail?: unknown }).detail : null) ?? text;
    throw new Error(formatErrorDetail(detail, res.status));
  }
  return data as T;
}

/** Download binary or text body; throws Error with API detail on failure. */
export async function fetchBlob(url: string, init?: RequestInit): Promise<Blob> {
  const res = await fetch(url, { cache: "no-store", credentials: "include", ...init });
  if (!res.ok) {
    const text = await res.text();
    let detail: unknown = text;
    try {
      const j = text ? JSON.parse(text) : null;
      if (j && typeof j === "object" && "detail" in j) detail = (j as { detail: unknown }).detail;
    } catch {
      /* use text */
    }
    throw new Error(formatErrorDetail(detail, res.status));
  }
  return res.blob();
}
