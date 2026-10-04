import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AUTH_DISABLED, loadAuth } from "./firebase.js";

const AuthContext = createContext(null);

// Fixed identity used when auth is disabled for local development.
const DEV_USER = { uid: "dev-user", email: "dev@local", displayName: "Dev User" };

export function AuthProvider({ children }) {
  const [user, setUser] = useState(AUTH_DISABLED ? DEV_USER : null);
  const [loading, setLoading] = useState(!AUTH_DISABLED);
  // Bumped when a reload finds the email newly verified, so consumers of
  // user.emailVerified (Firebase mutates the user object in place) re-render.
  const [verifiedTick, setVerifiedTick] = useState(0);

  // The Firebase SDK is loaded on demand (see firebase.js). Start straight
  // after mount so it's ready long before anyone clicks "Sign in" — the Google
  // popup must open synchronously inside the click, or browsers block it.
  const fb = useRef(null);
  useEffect(() => {
    if (AUTH_DISABLED) return;
    let unsubscribe = () => {};
    let cancelled = false;
    loadAuth()
      .then((mod) => {
        if (cancelled) return;
        fb.current = mod;
        unsubscribe = mod.onAuthStateChanged(mod.auth, (u) => {
          setUser(u);
          setLoading(false);
          // Upsert the user profile on the backend on first sight (fire-and-forget).
          if (u) import("./api.js").then(({ getMe }) => getMe().catch(() => {}));
        });
      })
      .catch(() => {
        // Couldn't load the auth SDK (offline?): show the signed-out state
        // rather than an endless spinner; a sign-in attempt retries the load.
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const value = useMemo(() => {
    // Run `fn(module)` with the auth SDK — synchronously when it's already
    // loaded (keeps the Google popup inside the click's user activation).
    const withAuth = (fn) => (fb.current ? fn(fb.current) : loadAuth().then((m) => fn((fb.current = m))));
    return {
      user,
      loading,
      verifiedTick,
      signIn: (email, password) => withAuth((m) => m.signInWithEmailAndPassword(m.auth, email, password)),
      // A new email/password account gets Firebase's verification email
      // straight away (best-effort: the banner offers a resend). Google
      // accounts arrive verified.
      signUp: (email, password) =>
        withAuth(async (m) => {
          const cred = await m.createUserWithEmailAndPassword(m.auth, email, password);
          try {
            await m.sendEmailVerification(cred.user);
          } catch {
            /* the banner's resend button covers a failed send */
          }
          return cred;
        }),
      resendVerification: () =>
        withAuth((m) => (m.auth.currentUser ? m.sendEmailVerification(m.auth.currentUser) : null)),
      // After the user follows the link in the email: reload the account,
      // refresh the ID token (it carries email_verified) and re-sync the
      // profile so invites waiting for this address activate. Resolves to
      // whether the address is now verified.
      refreshVerification: () =>
        withAuth(async (m) => {
          const current = m.auth.currentUser;
          if (!current) return false;
          await m.reload(current);
          if (!current.emailVerified) return false;
          await current.getIdToken(true);
          setVerifiedTick((n) => n + 1);
          const { getMe } = await import("./api.js");
          await getMe().catch(() => {});
          return true;
        }),
      signInWithGoogle: () => withAuth((m) => m.signInWithPopup(m.auth, m.googleProvider)),
      resetPassword: (email) => withAuth((m) => m.sendPasswordResetEmail(m.auth, email)),
      signOut: () => (AUTH_DISABLED ? Promise.resolve() : withAuth((m) => m.signOut(m.auth))),
    };
  }, [user, loading, verifiedTick]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
