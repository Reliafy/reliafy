// Firebase initialisation. The web config is a public client identifier (safe
// to ship in the bundle) and is read from Vite build-time env vars.
//
// When VITE_AUTH_DISABLED is set, we skip Firebase entirely so the app runs in
// local development with zero external setup (mirrors the backend AUTH_DISABLED
// flag). In that mode `auth` is null and the UI uses a fixed dev user.
import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

export const AUTH_DISABLED =
  String(import.meta.env.VITE_AUTH_DISABLED || "").toLowerCase() === "true";

// Auth-disabled builds (local dev, self-hosted instances) ship only the app —
// the marketing pages (guides, blog) aren't routed, so an in-app link to
// /guides would fall through to the app shell and bounce to /modelling. Point
// those links at the public site instead. Override the host with
// VITE_PUBLIC_SITE if you mirror the content elsewhere.
const PUBLIC_SITE =
  (import.meta.env.VITE_PUBLIC_SITE || "https://reliafy.com").replace(/\/+$/, "");

export function publicUrl(path = "/") {
  const p = path.startsWith("/") ? path : `/${path}`;
  return AUTH_DISABLED ? `${PUBLIC_SITE}${p}` : p;
}

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const auth = AUTH_DISABLED ? null : getAuth(initializeApp(firebaseConfig));
export const googleProvider = AUTH_DISABLED ? null : new GoogleAuthProvider();
