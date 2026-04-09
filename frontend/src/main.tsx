import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PreprocessingWorkspace from "./PreprocessingWorkspace";

const qc = new QueryClient();
createRoot(document.getElementById("preprocess-root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <PreprocessingWorkspace />
    </QueryClientProvider>
  </StrictMode>
);
