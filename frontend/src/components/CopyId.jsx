import { useState } from "react";

// A small monospace ID chip with copy-to-clipboard, shown on artifact detail
// pages so users can grab the id for the HTTP API / reliafy-client.
export default function CopyId({ id }) {
  const [copied, setCopied] = useState(false);
  if (!id) return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* text stays selectable */ }
  };
  return (
    <button type="button" className="copy-id" onClick={copy}
            title="Copy this ID for the API / reliafy-client">
      <span className="copy-id-k">ID</span>
      <code>{id}</code>
      {copied ? (
        <span className="copy-id-done">Copied ✓</span>
      ) : (
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor"
             strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15V5a2 2 0 0 1 2-2h10" />
        </svg>
      )}
    </button>
  );
}
