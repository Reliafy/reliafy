// The app's confirm dialog: what it says. The dialog itself is
// components/ConfirmProvider.jsx (`const confirm = useConfirm();
// if (!(await confirm(deleteConfirm({ kind: "diagram", name })))) return;`).
// The browser's own window.confirm is never used: it can't explain the
// consequence, can't be styled, and labels the action "OK".

// Words that don't say what the button does.
const VAGUE = new Set(["ok", "okay", "yes", "confirm", "continue", "sure"]);

// Fill in defaults and check a request. The confirm button names the action
// ("Delete diagram"), never "OK".
export function normaliseConfirm(opts = {}) {
  const title = String(opts.title || "").trim();
  if (!title) throw new Error("A confirm dialog needs a title.");
  const confirmLabel = String(opts.confirmLabel || "").trim();
  if (!confirmLabel || VAGUE.has(confirmLabel.toLowerCase())) {
    throw new Error(`Label the confirm button with the action, not "${confirmLabel || "(blank)"}".`);
  }
  return {
    title,
    body: opts.body ? String(opts.body) : "",
    confirmLabel,
    cancelLabel: String(opts.cancelLabel || "Cancel"),
    destructive: opts.destructive !== false,
  };
}

const quoted = (name) => `“${name || "Untitled"}”`;

// Deleting something you own: it's gone for good.
export function deleteConfirm({ kind, name, extra }) {
  return {
    title: `Delete this ${kind}?`,
    body: `${quoted(name)} will be deleted${extra ? `, ${extra}` : ""}. This can't be undone.`,
    confirmLabel: `Delete ${kind}`,
    destructive: true,
  };
}

// Removing a shared sample from your workspace: it's only hidden, and Settings
// brings it back.
export function removeSampleConfirm({ name }) {
  return {
    title: "Remove this sample?",
    body: `${quoted(name)} leaves your workspace. Other people still see it, and you can bring it back any time from Settings › Sample data.`,
    confirmLabel: "Remove sample",
    destructive: true,
  };
}

// Something someone shared with you: hiding it doesn't touch their copy.
export function removeSharedConfirm({ name }) {
  return {
    title: "Remove from your view?",
    body: `${quoted(name)} was shared with you. Removing it only hides it from you; the owner's copy stays as it is.`,
    confirmLabel: "Remove from view",
    destructive: true,
  };
}

// The usual delete: a sample is removed (hidden), something shared with you is
// hidden from your view, and your own is deleted.
export function deleteOrRemoveConfirm(item, kind, { name, extra } = {}) {
  const label = name ?? item.name;
  if (item.is_sample) return removeSampleConfirm({ name: label });
  if (item.read_only) return removeSharedConfirm({ name: label });
  return deleteConfirm({ kind, name: label, extra });
}
