import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the React dev server runs on :5173 and proxies API calls
// to the FastAPI backend on :8000. In production the backend serves the built
// files directly, so everything is one origin / one port.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
