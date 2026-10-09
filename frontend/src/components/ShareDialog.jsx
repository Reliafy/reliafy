import { useCallback, useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import {
  createShare, listShares, revokeShare,
  createPublicLink, listPublicLinks, updatePublicLink, revokePublicLink,
} from "../api.js";
import Chip from "./ui/Chip.jsx";

// Collections with a public read-only renderer at /p/:token.
const PUBLIC_LINKABLE = new Set([
  "models", "datasets", "degradation_models", "strategy_analyses", "rcm_studies", "fleets", "rbds",
  "recurrent_models",
]);

// Expiry choices for a new public link ("" = until revoked).
const EXPIRY_OPTIONS = [
  ["", "Never"],
  ["1", "1 day"],
  ["7", "7 days"],
  ["30", "30 days"],
  ["90", "90 days"],
  ["365", "1 year"],
];

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

const LockIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </svg>
);

const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false; // clipboard can be unavailable; the text is selectable
  }
}

// A generated passphrase, shown once (only its hash is stored).
function PassphraseNote({ phrase, onDismiss }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="pl-phrase" role="status">
      <div className="pl-phrase-row">
        <code>{phrase}</code>
        <button
          type="button"
          className="secondary"
          onClick={async () => setCopied(await copyText(phrase))}
        >
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>
      <p>
        Shown only now. Send the password separately from the link (say, the
        link by email and the password by message).{" "}
        <button type="button" className="link" onClick={onDismiss}>Done</button>
      </p>
    </div>
  );
}

// One existing public link: its URL, label, expiry and password state, with
// copy, password changes and revoke.
function LinkRow({ link, phrase, busy, onCopy, copied, onChange, onRevoke, onDismissPhrase }) {
  const url = `${window.location.origin}${link.path}`;
  return (
    <div className="pl-link">
      <div className="pl-link-head">
        <span className="pl-link-label">{link.label || "Public link"}</span>
        {link.protected && (
          <Chip tone="accent" title="Viewers need the password">
            <LockIcon /> Password
          </Chip>
        )}
        <Chip>{link.expires_at ? `Expires ${fmtDate(link.expires_at)}` : "No expiry"}</Chip>
        <button
          type="button"
          className="pl-revoke"
          title="Revoke this link"
          aria-label="Revoke this link"
          disabled={busy}
          onClick={() => onRevoke(link)}
        >
          <TrashIcon />
        </button>
      </div>
      <div className="pl-link-url">
        <input type="text" readOnly value={url} onFocus={(e) => e.target.select()} aria-label="Link URL" />
        <button type="button" onClick={() => onCopy(link, url)}>{copied ? "Copied ✓" : "Copy"}</button>
      </div>
      <div className="pl-link-acts">
        {link.protected ? (
          <>
            <button type="button" className="link" disabled={busy}
              onClick={() => onChange(link, { generate_password: true })}>
              New password
            </button>
            <button type="button" className="link" disabled={busy}
              onClick={() => onChange(link, { remove_password: true })}>
              Remove password
            </button>
          </>
        ) : (
          <button type="button" className="link" disabled={busy}
            onClick={() => onChange(link, { generate_password: true })}>
            Add a password
          </button>
        )}
      </div>
      {phrase && <PassphraseNote phrase={phrase} onDismiss={onDismissPhrase} />}
    </div>
  );
}

// Public links: anyone with the URL can view, no account needed. An
// artifact can have several (one per recipient), each with an optional
// label, expiry and password, each revocable on its own.
function PublicLinks({ collection, artifactId, onError }) {
  const [links, setLinks] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(null); // token
  const [phrase, setPhrase] = useState(null); // { token, passphrase }
  const [label, setLabel] = useState("");
  const [expires, setExpires] = useState("");
  const [requirePassword, setRequirePassword] = useState(false);
  const [ownPassword, setOwnPassword] = useState("");

  const refresh = useCallback(() => {
    listPublicLinks(collection, artifactId).then((d) => setLinks(d.links || [])).catch(() => setLinks([]));
  }, [collection, artifactId]);
  useEffect(() => refresh(), [refresh]);

  const run = async (fn) => {
    setBusy(true);
    onError(null);
    try {
      await fn();
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onCreate = () =>
    run(async () => {
      const typed = ownPassword.trim();
      const link = await createPublicLink(collection, artifactId, {
        label: label.trim() || null,
        expires_in_days: expires ? Number(expires) : null,
        ...(requirePassword ? (typed ? { password: typed } : { generate_password: true }) : {}),
      });
      setPhrase(link.passphrase ? { token: link.token, passphrase: link.passphrase } : null);
      setLabel("");
      setExpires("");
      setRequirePassword(false);
      setOwnPassword("");
      refresh();
    });

  const onChange = (link, changes) =>
    run(async () => {
      const updated = await updatePublicLink(link.token, changes);
      setPhrase(updated.passphrase ? { token: link.token, passphrase: updated.passphrase } : null);
      refresh();
    });

  const onRevoke = (link) =>
    run(async () => {
      await revokePublicLink(link.token);
      if (phrase?.token === link.token) setPhrase(null);
      refresh();
    });

  const onCopy = async (link, url) => {
    if (await copyText(url)) {
      setCopied(link.token);
      setTimeout(() => setCopied((t) => (t === link.token ? null : t)), 2000);
    }
  };

  const tooShort = requirePassword && ownPassword.trim() !== "" && ownPassword.trim().length < 8;

  return (
    <div className="pl-section">
      <label className="field-label">Public links</label>
      <p className="muted-line" style={{ margin: "0.2rem 0 0.5rem" }}>
        Anyone with a link can view it — no account needed. Read-only,
        revocable, and it includes the linked analyses this one relies on.
      </p>

      {(links || []).map((link) => (
        <LinkRow
          key={link.token}
          link={link}
          busy={busy}
          copied={copied === link.token}
          phrase={phrase?.token === link.token ? phrase.passphrase : null}
          onCopy={onCopy}
          onChange={onChange}
          onRevoke={onRevoke}
          onDismissPhrase={() => setPhrase(null)}
        />
      ))}

      <div className="pl-new">
        <div className="pl-new-row">
          <label className="login-field pl-new-label">
            <span>{links?.length ? "New link · label" : "Label (optional)"}</span>
            <input
              type="text"
              value={label}
              maxLength={80}
              placeholder="e.g. for the client"
              onChange={(e) => setLabel(e.target.value)}
            />
          </label>
          <label className="login-field pl-new-expiry">
            <span>Expires</span>
            <select value={expires} onChange={(e) => setExpires(e.target.value)}>
              {EXPIRY_OPTIONS.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
            </select>
          </label>
        </div>
        <label className="pl-check">
          <input
            type="checkbox"
            checked={requirePassword}
            onChange={(e) => setRequirePassword(e.target.checked)}
          />
          Require password
        </label>
        {requirePassword && (
          <label className="login-field">
            <span>Password</span>
            <input
              type="text"
              value={ownPassword}
              autoComplete="off"
              placeholder="Leave blank to generate one"
              onChange={(e) => setOwnPassword(e.target.value)}
            />
          </label>
        )}
        {tooShort && <p className="muted-line pl-hint">Use at least 8 characters, or leave it blank.</p>}
        <button type="button" className="secondary" onClick={onCreate} disabled={busy || tooShort}>
          {busy ? "Working…" : links?.length ? "Create another link" : "Create public link"}
        </button>
      </div>
    </div>
  );
}

// Share an artifact (view-only) with any registered user by email, and manage
// existing shares. Linked evidence/datasets are readable for recipients too,
// resolved live server-side.
export default function ShareDialog({ collection, artifactId, name, onClose }) {
  const [shares, setShares] = useState(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);

  const linkable = PUBLIC_LINKABLE.has(collection);

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
      className="modal-sm share-modal"
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

      {linkable && <PublicLinks collection={collection} artifactId={artifactId} onError={setError} />}
    </Modal>
  );
}

// The share button that opens the dialog — render on detail pages when the
// artifact is the user's own (not read-only, personal workspace).
export function ShareButton({ collection, artifactId, name, readOnly, className = "secondary" }) {
  const { workspace } = useWorkspace();
  const [open, setOpen] = useState(false);
  // Only your own personal artifacts are sharable (team artifacts are already
  // shared with the team; read-only means it isn't yours).
  if (readOnly || workspace !== "personal") return null;
  return (
    <>
      <button className={className} onClick={() => setOpen(true)}>Share</button>
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
