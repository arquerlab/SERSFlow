import { fetchJson } from "./api.js";

export function getSelectedPaths(plotFileSelectorsEl) {
  const paths = [];
  const seen = new Set();
  const selects = plotFileSelectorsEl ? plotFileSelectorsEl.querySelectorAll("select") : [];
  for (const s of selects) {
    const v = (s.value || "").trim();
    if (!v) continue;
    if (seen.has(v)) continue;
    seen.add(v);
    paths.push(v);
  }
  return paths;
}

export async function fetchFigure(endpoint, payload) {
  const data = await fetchJson(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const fig = data.figure;
  if (!fig || !fig.data || !fig.layout) throw new Error("Invalid figure JSON returned by server.");
  return fig;
}

export async function plotFromEndpoint({ plotDiv, endpoint, payload, showError, clearError }) {
  clearError();
  try {
    const fig = await fetchFigure(endpoint, payload);
    Plotly.react(plotDiv, fig.data, fig.layout, { responsive: true });
  } catch (e) {
    showError(String(e && e.message ? e.message : e));
  }
}

