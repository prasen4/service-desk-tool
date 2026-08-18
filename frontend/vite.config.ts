import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output lives inside the installed Python package so FastAPI can serve
// it directly without reaching outside the package directory in production.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/tech_desk/api/web/dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
      },
    },
  },
});
