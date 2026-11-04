// A list row's click: the name cell holds the real link (RowLink), and the
// rest of the row opens the same address for convenience. A ctrl/cmd or
// middle click on the row opens a new tab, as it would on the link itself.
export function rowOpen(navigate, to) {
  return (e) => {
    if (e && (e.metaKey || e.ctrlKey || e.button === 1)) {
      window.open(to, "_blank", "noopener");
      return;
    }
    // Selecting text in a row shouldn't open it.
    if (typeof window !== "undefined" && window.getSelection && String(window.getSelection()).length > 0) return;
    navigate(to);
  };
}
