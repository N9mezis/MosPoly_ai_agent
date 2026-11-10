import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev-режиме запросы к API проксируются на бэкенд.
// Локально без Docker: VITE_API_PROXY=http://localhost:8000 npm run dev
const target = process.env.VITE_API_PROXY ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": target,
      "/healthz": target,
      "/readyz": target,
      "/docs": target,
      "/openapi.json": target,
    },
  },
});
