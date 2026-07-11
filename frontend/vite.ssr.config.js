import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Config for the build-time prerender bundle (see scripts/prerender.mjs).
// Firebase is swapped for a null stub: server renders never run effects, so
// the marketing pages don't need a real auth handle — and firebase's browser
// entry points don't belong in a Node bundle.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      [fileURLToPath(new URL("./src/firebase.js", import.meta.url))]:
        fileURLToPath(new URL("./src/firebase.ssr-stub.js", import.meta.url)),
    },
  },
  build: {
    ssr: "src/prerender-entry.jsx",
    outDir: "dist-ssr",
    emptyOutDir: true,
  },
});
