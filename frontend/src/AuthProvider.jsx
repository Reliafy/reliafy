import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  signOut as fbSignOut,
  sendPasswordResetEmail,
  onAuthStateChanged,
} from "firebase/auth";
import { auth, googleProvider, AUTH_DISABLED } from "./firebase.js";

const AuthContext = createContext(null);

// Fixed identity used when auth is disabled for local development.
const DEV_USER = { uid: "dev-user", email: "dev@local", displayName: "Dev User" };

export function AuthProvider({ children }) {
  const [user, setUser] = useState(AUTH_DISABLED ? DEV_USER : null);
  const [loading, setLoading] = useState(!AUTH_DISABLED);

  useEffect(() => {
    if (AUTH_DISABLED) return;
    return onAuthStateChanged(auth, (u) => {
      setUser(u);
      setLoading(false);
      // Upsert the user profile on the backend on first sight (fire-and-forget).
      if (u) import("./api.js").then(({ getMe }) => getMe().catch(() => {}));
    });
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      signIn: (email, password) => signInWithEmailAndPassword(auth, email, password),
      signUp: (email, password) => createUserWithEmailAndPassword(auth, email, password),
      signInWithGoogle: () => signInWithPopup(auth, googleProvider),
      resetPassword: (email) => sendPasswordResetEmail(auth, email),
      signOut: () => (AUTH_DISABLED ? Promise.resolve() : fbSignOut(auth)),
    }),
    [user, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
