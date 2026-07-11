import { useCallback, useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import { createShare, listShares, revokeShare } from "../api.js";

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

// Share an artifact (view-only) with any registered user by email, and manage
// existing shares. Linked evidence/datasets are readable for recipients too,
// resolved live server-side.
export default function ShareDialog({ collection, artifactId, name, onClose }) {
  const [shares, setShares] = useState(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);

  const refresh = useCallback(() => {
    listShares(collection, artifactId)
      .then((d) => setShares(d.shares))
      .catch((e) => setError(e.message));
  }, [collection, artifactId]);
  useEffect(() => refresh(), [refresh]);

  const onShare = async () => {
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await createShare(collection, artifactId, email.trim());
      setNote(`Shared with ${email.trim()} — they'll see it in their workspace, read-only.`);
      setEmail("");
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onRevoke = async (s) => {
    if (!window.confirm(`Stop sharing with ${s.email}?`)) return;
    await revokeShare(s.id);
    refresh();
  };

  return (
    <Modal
      title={`Share — ${name}`}
      className="modal-sm"
      locked={busy}
      onClose={onClose}
      footer={
        <div style={{ display: "flex", gap: "0.6rem", marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose}>Done</button>
        </div>
      }
    >
      <p className="muted-line" style={{ marginTop: 0 }}>
        Recipients get a read-only view — including any linked analyses this
        one relies on. They need a Reliafy account. You can revoke at any time.
      </p>
      <div className="row" style={{ gap: "0.6rem", alignItems: "flex-end" }}>
        <label className="login-field" style={{ flex: 1 }}>
          <span>Share with (email)</span>
          <input
            type="email"
            autoFocus
            value={email}
            placeholder="colleague@company.com"
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onShare()}
          />
        </label>
        <button onClick={onShare} disabled={busy || !email.trim()}>
          {busy ? "Sharing…" : "Share"}
        </button>
      </div>
      {error && <div className="error" style={{ marginTop: "0.6rem" }}>{error}</div>}
      {note && <p className="muted-line" style={{ marginBottom: 0 }}>{note}</p>}

      {shares && shares.length > 0 && (
        <div style={{ marginTop: "0.9rem" }}>
          <label className="field-label">Shared with</label>
          {shares.map((s) => (
            <div key={s.id} className="share-row">
              <span>{s.email}</span>
              <button className="act del" title="Revoke" onClick={() => onRevoke(s)}>
                <TrashIcon />
              </button>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

// The share button that opens the dialog — render on detail pages when the
// artifact is the user's own (not read-only, personal workspace).
export function ShareButton({ collection, artifactId, name, readOnly }) {
  const { workspace } = useWorkspace();
  const [open, setOpen] = useState(false);
  // Only your own personal artifacts are sharable (team artifacts are already
  // shared with the team; read-only means it isn't yours).
  if (readOnly || workspace !== "personal") return null;
  return (
    <>
      <button className="secondary" onClick={() => setOpen(true)}>Share</button>
      {open && (
        <ShareDialog
          collection={collection}
          artifactId={artifactId}
          name={name}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
