// Auth configuration shared across the app — deliberately light. The Firebase
// SDK itself (~120 KB gzipped) lives in firebaseAuth.js and is loaded on
// demand via loadAuth(), so public pages paint without it; AuthProvider starts
// loading it straight after mount, well before anyone can click "Sign in".
//
// When VITE_AUTH_DISABLED is set, we skip Firebase entirely so the app runs in
// local development with zero external setup (mirrors the backend AUTH_DISABLED
// flag). In that mode loadAuth() resolves to null and the UI uses a fixed dev
// user.
export const AUTH_DISABLED =
  String(import.meta.env.VITE_AUTH_DISABLED || "").toLowerCase() === "true";

// Auth-disabled builds (local dev, self-hosted instances) ship only the app,
// the how-to guides and share pages: the marketing pages (blog, Learn,
// Reference, What's new) aren't routed, so an in-app link to one would fall
// through to the app shell and bounce to /home. Point those links at the
// public site instead; guides stay local. Override the host with
// VITE_PUBLIC_SITE if you mirror the content elsewhere.
const PUBLIC_SITE =
  (import.meta.env.VITE_PUBLIC_SITE || "https://reliafy.com").replace(/\/+$/, "");

// Paths every build routes itself (App.jsx): never sent to the public site.
export const LOCAL_PUBLIC_PREFIXES = ["/guides", "/p"];

export function isLocalPublicPath(path) {
  const p = String(path || "").split(/[?#]/)[0];
  return LOCAL_PUBLIC_PREFIXES.some((x) => p === x || p.startsWith(`${x}/`));
}

export function publicUrl(path = "/") {
  const p = path.startsWith("/") ? path : `/${path}`;
  return AUTH_DISABLED && !isLocalPublicPath(p) ? `${PUBLIC_SITE}${p}` : p;
}

let authModule = null;

// The Firebase auth module ({ auth, googleProvider, signInWithPopup, … }),
// loaded once. Resolves to null when auth is disabled.
export function loadAuth() {
  if (AUTH_DISABLED) return Promise.resolve(null);
  if (!authModule) {
    authModule = import("./firebaseAuth.js").catch((err) => {
      authModule = null; // let the next call retry (e.g. after a network blip)
      throw err;
    });
  }
  return authModule;
}
