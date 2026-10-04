import { useState } from "react";
import { useAuth } from "../AuthProvider.jsx";
import { AUTH_DISABLED } from "../firebase.js";

const DISMISS_KEY = "reliafy.verifyBannerDismissed";

function wasDismissed() {
  try {
    return window.sessionStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

// A gentle reminder for email/password accounts whose address isn't verified
// yet. Team invites and items shared to an email address only reach an
// account once that address is verified (Google sign-ins arrive verified).
export default function VerifyEmailBanner() {
  const { user, resendVerification, refreshVerification } = useAuth();
  const [dismissed, setDismissed] = useState(wasDismissed);
  const [status, setStatus] = useState(null); // null | sending | sent | checking | still | error

  if (AUTH_DISABLED || !user || user.emailVerified || dismissed || !user.email) return null;
  const passwordAccount = (user.providerData || []).some((p) => p?.providerId === "password");
  if (!passwordAccount) return null;

  const onResend = async () => {
    setStatus("sending");
    try {
      await resendVerification();
      setStatus("sent");
    } catch {
      setStatus("error");
    }
  };

  const onCheck = async () => {
    setStatus("checking");
    try {
      const verified = await refreshVerification();
      setStatus(verified ? null : "still");
    } catch {
      setStatus("error");
    }
  };

  const onDismiss = () => {
    try {
      window.sessionStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* dismiss for this render only */
    }
    setDismissed(true);
  };

  const busy = status === "sending" || status === "checking";
  return (
    <div className="verify-banner" role="status">
      <div className="verify-banner-text">
        <b>Please verify your email address.</b> We sent a link to <b>{user.email}</b>. Team
        invites and items people share with that address reach you once it's verified.
        {status === "sent" && <span className="verify-banner-note"> Sent — check your inbox (and spam folder).</span>}
        {status === "still" && <span className="verify-banner-note"> Not verified yet — open the link in the email, then try again.</span>}
        {status === "error" && <span className="verify-banner-note"> That didn't work — please try again in a minute.</span>}
      </div>
      <div className="verify-banner-actions">
        <button type="button" className="secondary" disabled={busy} onClick={onResend}>
          {status === "sending" ? "Sending…" : "Resend email"}
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={onCheck}>
          {status === "checking" ? "Checking…" : "I've verified"}
        </button>
        <button type="button" className="verify-banner-close" aria-label="Dismiss" onClick={onDismiss}>
          ✕
        </button>
      </div>
    </div>
  );
}
