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
    rollupOptions: {
      output: {
        // Plotly (~4.5 MB) in its own chunk: its content hash then only changes when Plotly itself is upgraded,
        // so browsers keep it cached across app releases and git stops storing a new copy on every build.
        manualChunks(id: string) {
          if (id.includes("plotly.js-dist-min")) return "plotly";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/auth": "http://localhost:8000",
      "/sessions": "http://localhost:8000",
      "/pipeline": "http://localhost:8000",
      "/pipelines": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
      "/io": "http://localhost:8000",
      "/plot": "http://localhost:8000",
      "/analysis": "http://localhost:8000",
      "/explore": "http://localhost:8000",
      "/fitting": "http://localhost:8000",
      // Only proxy legacy static assets we still depend on at runtime.
      // IMPORTANT: do NOT proxy `/static/preprocess-dist/` because Vite serves the React app at that base path in dev.
      "/static/styles.css": "http://localhost:8000",
      "/static/ui": "http://localhost:8000",
    },
  },
});
