import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app always calls /api/*. In dev Vite proxies it to the API; in docker nginx does.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL || "http://localhost:8010",
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
