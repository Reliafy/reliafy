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

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const auth = AUTH_DISABLED ? null : getAuth(initializeApp(firebaseConfig));
export const googleProvider = AUTH_DISABLED ? null : new GoogleAuthProvider();
