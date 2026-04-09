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
      "/static": "http://localhost:8000",
    },
  },
});
