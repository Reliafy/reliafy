// The Modelling tab's work that fills the Explorer's table area, the tree kept beside it, instead
// of a dialog (Derryn, 9 Nov 2026: "It shouldn't be a modal itself"; the parts count "should also
// be the same, where it fills up the table area"). Each has its own address, so a reload keeps it
// open, and its words for leaving it with something changed.

export const TABLE_PANES = {
  fit: {
    param: "fit",
    discard: {
      title: "Discard this fit?", body: "What you've chosen in Fit a life model isn't saved.",
      confirmLabel: "Discard the fit", cancelLabel: "Keep fitting",
    },
  },
  predict: {
    param: "predict",
    discard: {
      title: "Discard this prediction?", body: "The part types you've chosen in the prediction aren't saved.",
      confirmLabel: "Discard the prediction", cancelLabel: "Keep predicting",
    },
  },
};

// Which pane the address asks for ({kind, id}), or null. One at a time: a fit first, as it was
// the first.
export function paneFromQuery(params) {
  for (const [kind, p] of Object.entries(TABLE_PANES)) {
    const id = params?.get?.(p.param);
    if (id) return { kind, id };
  }
  return null;
}

// Every pane's address parameter, for clearing them all.
export const PANE_PARAMS = Object.values(TABLE_PANES).map((p) => p.param);
