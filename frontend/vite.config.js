import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { writeFileSync } from "node:fs";

// With VITE_BUILD_ID set (the Docker build), the same id the bundle carries is
// written beside it for the server to send as X-Reliafy-Build.
const buildIdFile = () => ({
  name: "reliafy-build-id",
  apply: "build",
  closeBundle() {
    if (process.env.VITE_BUILD_ID) writeFileSync("dist/build-id.txt", process.env.VITE_BUILD_ID);
  },
});

// During development the React dev server runs on :5173 and proxies API calls
// to the FastAPI backend on :8000. In production the backend serves the built
// files directly, so everything is one origin / one port.
export default defineConfig({
  plugins: [react(), buildIdFile()],
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
