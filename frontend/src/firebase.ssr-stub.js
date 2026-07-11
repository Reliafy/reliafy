// SSR stand-in for firebase.js used only by the build-time prerender (see
// vite.ssr.config.js). The marketing pages never touch Firebase during a
// server render — effects don't run — so a null auth handle is all they need.
export const AUTH_DISABLED = false;
export const auth = null;
export const googleProvider = null;
