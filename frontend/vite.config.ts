/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

const apiTarget = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    // Same origin in development, so cookies and the CSRF header work without CORS.
    proxy: {
      "/api": { target: apiTarget, changeOrigin: false },
      "/health": { target: apiTarget },
      "/ready": { target: apiTarget },
    },
    fs: { allow: [".."] },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: apiTarget }, "/health": { target: apiTarget }, "/ready": { target: apiTarget } },
  },
  build: {
    target: "es2022",
    sourcemap: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // Only the libraries every page uses are grouped. Charts and Markdown stay with the lazy
        // pages that import them, so the home page never downloads them.
        manualChunks(id) {
          if (id.includes("node_modules/framer-motion") || id.includes("node_modules/motion-")) return "motion";
          if (
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react/") ||
            id.includes("node_modules/react-router") ||
            id.includes("node_modules/scheduler")
          )
            return "react";
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
