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

const qc = new QueryClient();
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
