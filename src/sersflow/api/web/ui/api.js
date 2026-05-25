export async function fetchText(url, options) {
  const res = await fetch(url, { cache: "no-store", ...options });
  const text = await res.text();
  return { res, text };
}

export async function fetchJson(url, options) {
  const { res, text } = await fetchText(url, options);
  if (!res.ok) throw new Error(text || `Request failed (${res.status})`);
  return JSON.parse(text || "{}");
}

