import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Logo from "../components/Logo.jsx";
import { useAuth } from "../AuthProvider.jsx";

// Friendly messages for the common Firebase auth error codes.
const MESSAGES = {
  "auth/invalid-credential": "Incorrect email or password.",
  "auth/invalid-email": "That doesn't look like a valid email.",
  "auth/email-already-in-use": "An account with that email already exists.",
  "auth/weak-password": "Password should be at least 6 characters.",
  "auth/popup-closed-by-user": "Sign-in was cancelled.",
  "auth/unauthorized-domain": "This domain isn't authorised for sign-in yet.",
  "auth/operation-not-allowed": "Google sign-in isn't enabled yet — use email and password.",
  "auth/user-not-found": "No account with that email.",
  "auth/missing-email": "Enter your email first.",
};

export default function Login() {
  const { signIn, signUp, signInWithGoogle, resetPassword } = useAuth();
  const navigate = useNavigate();
  // "Get started" CTAs link to /login?signup so new users land on the
  // create-account form directly instead of hunting for the toggle.
  const [params] = useSearchParams();
  const [mode, setMode] = useState(params.has("signup") ? "signup" : "signin"); // 'signin' | 'signup' | 'reset'
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const fail = (e) => setError(MESSAGES[e?.code] || e?.message || "Something went wrong.");
  const switchMode = (m) => { setMode(m); setError(null); setNotice(null); };

  const onSubmit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "reset") {
        await resetPassword(email);
        setNotice("Reset link sent — check your email (and spam folder).");
        return;
      }
      if (mode === "signin") await signIn(email, password);
      else await signUp(email, password);
      navigate("/modelling");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const onGoogle = async () => {
    setBusy(true);
    setError(null);
    try {
      await signInWithGoogle();
      navigate("/modelling");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <Logo size={34} />
          <span className="brand-name">Reliafy</span>
        </div>
        <h1 className="login-h1">
          {mode === "signin" ? "Sign in" : mode === "signup" ? "Create your account" : "Reset your password"}
        </h1>
        <p className="login-sub">
          {mode === "reset"
            ? "Enter your account email and we'll send you a reset link."
            : "Fit reliability models and build RBDs — your work, private to you."}
        </p>

        {mode !== "reset" && (
        <button type="button" className="google-btn" onClick={onGoogle} disabled={busy}>
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
            <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
            <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z" />
            <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
          </svg>
          Continue with Google
        </button>
        )}

        {mode !== "reset" && <div className="login-or"><span>or</span></div>}

        <form onSubmit={onSubmit} className="login-form">
          <label className="login-field">
            <span>Email</span>
            <input type="email" value={email} autoComplete="email" required
              onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          </label>
          {mode !== "reset" && (
            <label className="login-field">
              <span>Password</span>
              <input type="password" value={password}
                autoComplete={mode === "signin" ? "current-password" : "new-password"} required
                onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
            </label>
          )}
          {mode === "signin" && (
            <div className="login-forgot">
              <button type="button" onClick={() => switchMode("reset")}>Forgot password?</button>
            </div>
          )}
          {error && <div className="error" style={{ marginTop: 0 }}>{error}</div>}
          {notice && <div className="login-notice">{notice}</div>}
          <button type="submit" disabled={busy} style={{ width: "100%", justifyContent: "center" }}>
            {busy ? "Please wait…" : mode === "signin" ? "Sign in" : mode === "signup" ? "Create account" : "Send reset link"}
          </button>
        </form>

        <div className="login-toggle">
          {mode === "signin" ? (
            <>New to Reliafy?{" "}
              <button type="button" onClick={() => switchMode("signup")}>Create an account</button>
            </>
          ) : (
            <>Already have an account?{" "}
              <button type="button" onClick={() => switchMode("signin")}>Sign in</button>
            </>
          )}
        </div>

        <p className="login-legal">
          By continuing you agree to the <Link to="/terms">Terms of Service</Link> and{" "}
          <Link to="/privacy">Privacy Policy</Link>.
        </p>
      </div>
    </div>
  );
}
