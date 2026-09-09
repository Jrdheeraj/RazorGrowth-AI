import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// ---------------------------------------------------------------------------
// RazorGrowth AI — frontend build configuration.
//
// Dev server proxies /api to the FastAPI backend so the browser talks
// same-origin and no CORS setup is required locally. In production builds
// the app uses VITE_API_BASE_URL (empty = same-origin behind a reverse proxy).
// ---------------------------------------------------------------------------
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        // Override when the backend lives on another host/interface,
        // e.g. VITE_PROXY_TARGET=http://172.x.x.x:8000 (WSL → Windows setups).
        target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
});
