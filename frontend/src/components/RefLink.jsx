import { getEntry } from "../reference.js";
import { openReference } from "./HelpButton.jsx";

// A small "?" that opens the model reference for `entryId` in the Help drawer.
// Renders nothing when there's no entry (e.g. the "best fit" pseudo-option), so
// callers can drop it in beside any picker without guarding.
export default function RefLink({ entryId, label = "What is this model?" }) {
  if (!entryId || !getEntry(entryId)) return null;
  return (
    <button
      type="button"
      className="ref-link"
      title={label}
      aria-label={label}
      onClick={() => openReference(entryId)}
    >
      ?
    </button>
  );
}
