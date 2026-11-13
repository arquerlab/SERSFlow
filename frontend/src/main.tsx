import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter } from "react-router-dom";
import AppShell from "./AppShell";

function ensureLegacyStylesLoaded() {
  const href = "/static/styles.css";
  const alreadyLoaded = Array.from(document.querySelectorAll('link[rel="stylesheet"]')).some(
    (l) => (l as HTMLLinkElement).href && (l as HTMLLinkElement).href.endsWith(href)
  );
  if (alreadyLoaded) return;

  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
}

// Mutations invalidate their queries explicitly, so refetching every query (full dataset spectra lists, up to
// 500 pipelines, run lists) each time the window regains focus only costs requests.
const qc = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});
ensureLegacyStylesLoaded();
createRoot(document.getElementById("preprocess-root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <HashRouter>
        <AppShell />
      </HashRouter>
    </QueryClientProvider>
  </StrictMode>
);
