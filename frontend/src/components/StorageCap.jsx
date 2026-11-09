import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getBilling } from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { errorText, isCapRefusal, storageCapReached } from "../plan.js";

// A list page's note when the Free plan's storage limit for ``kind`` is used
// up: what the limit is, that Pro removes it, and the upgrade link. ``one`` and
// ``many`` name the item ("saved reliability prediction"). ``refreshKey``
// re-reads the count (after a delete). Shows nothing on Pro or self-hosted.
export function StorageCapNotice({ kind, one, many, refreshKey = 0 }) {
  const config = useAppConfig();
  const [hit, setHit] = useState(null);
  useEffect(() => {
    if (!config.billing) return undefined;
    let alive = true;
    getBilling().then((b) => { if (alive) setHit(storageCapReached(b, kind)); }).catch(() => {});
    return () => { alive = false; };
  }, [config.billing, kind, refreshKey]);
  if (!hit) return null;
  return (
    <div className="card upgrade-nudge" role="status">
      <p>
        You've reached the free-plan limit of {hit.cap} {hit.cap === 1 ? one : many}.{" "}
        <Link to="/billing">Upgrade to Pro</Link> for unlimited {many.replace(/^saved /, "")}, or delete one you no
        longer need to save another. Shared samples don't count.
      </p>
    </div>
  );
}

// A refused save past the cap (the server's 402 ``code: "cap"``): its message
// with the upgrade link. Anything else renders nothing.
export function CapRefusal({ error }) {
  if (!isCapRefusal(error)) return null;
  return (
    <div className="card upgrade-nudge" role="alert">
      <p>{error.message} <Link to="/billing">Upgrade to Pro</Link></p>
    </div>
  );
}

// A page's or dialog's error line that turns a refused save past the cap into
// the upgrade card (CapRefusal) and shows anything else as plain text.
// ``error`` is an Error (keep the object: its ``code`` says which) or a
// string; ``className`` styles the plain line ("error", or "card error").
export function ErrorNotice({ error, className = "error", role, style }) {
  if (!error) return null;
  if (isCapRefusal(error)) return <CapRefusal error={error} />;
  return <div className={className} role={role} style={style}>{errorText(error)}</div>;
}
