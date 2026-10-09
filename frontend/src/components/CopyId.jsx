import { useState } from "react";

// Copy an artifact's ID (for the HTTP API / reliafy-client) to the clipboard.
// Returns [copied, copy]: copied is true for a moment after a copy.
export function useCopyId(id) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* the ID stays visible in the item to select by hand */ }
  };
  return [copied, copy];
}

// "Copy ID" in a page's ⋯ menu (#303): the ID moved out of the header. The
// menu stays open for the moment it says "Copied", and the ID shows under the
// label so it can be read or selected.
export default function CopyIdItem({ id }) {
  const [copied, copy] = useCopyId(id);
  if (!id) return null;
  return (
    <button
      type="button"
      className="ovm-item ovm-copy-id"
      title="Copy this ID for the API / reliafy-client"
      onClick={(e) => {
        e.stopPropagation();
        copy();
      }}
    >
      <span>{copied ? "Copied ✓" : "Copy ID"}</span>
      <code>{id}</code>
    </button>
  );
}
