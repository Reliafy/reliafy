// SSR stand-in for firebase.js used only by the build-time prerender (see
// vite.ssr.config.js). The marketing pages never touch Firebase during a
// server render — effects don't run — so the auth SDK is never loaded.
export const AUTH_DISABLED = false;

export function publicUrl(path = "/") {
  return path.startsWith("/") ? path : `/${path}`;
}

export function loadAuth() {
  return Promise.resolve(null);
}
