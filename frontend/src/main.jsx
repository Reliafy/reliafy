import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// After a deploy, a page loaded from an older build (an open tab, or a copy the
// browser kept) asks for code/style chunks by their old hashed names — which no
// longer exist — and the app crashes ("Unable to preload CSS for
// /assets/AppShell-….css"). Vite reports that as `vite:preloadError`; reload once
// to pick up the current build. The sessionStorage guard stops a reload loop if
// a chunk is genuinely missing: a second failure within a minute is left to
// surface normally.
window.addEventListener("vite:preloadError", (event) => {
  const KEY = "reliafy:stale-build-reload";
  let last = 0;
  try {
    last = Number(sessionStorage.getItem(KEY) || 0);
  } catch {
    /* storage unavailable: still worth one reload */
  }
  if (Date.now() - last < 60_000) return;
  try {
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    /* ignore */
  }
  event.preventDefault();
  window.location.reload();
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
