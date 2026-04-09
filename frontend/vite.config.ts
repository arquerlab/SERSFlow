import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: "/static/preprocess-dist/",
  build: {
    outDir: "../src/sersflow/api/web/preprocess-dist",
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/datasets": "http://localhost:8000",
      "/sessions": "http://localhost:8000",
      "/pipeline": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
      "/io": "http://localhost:8000",
      "/plot": "http://localhost:8000",
      // Only proxy legacy static assets we still depend on at runtime.
      // IMPORTANT: do NOT proxy `/static/preprocess-dist/` because Vite serves the React app at that base path in dev.
      "/static/styles.css": "http://localhost:8000",
      "/static/ui": "http://localhost:8000",
    },
  },
});
