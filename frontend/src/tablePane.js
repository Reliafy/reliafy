// The Modelling tab's work that fills the Explorer's table area, the tree kept beside it, instead
// of a dialog (Derryn, 9 Nov 2026: "It shouldn't be a modal itself"; the parts count "should also
// be the same, where it fills up the table area"; an RBD should "fill up that table pane with the
// existing RBD builder"). Each has its own address, so a reload keeps it open, and its words for
// leaving it with something changed.
//
// A fit and a prediction are for a position (?fit=<position id>); an RBD is a diagram linked to a
// position (?rbd=<RBD id>&on=<position id>): `on` names the position whose row it opens beside.

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
  rbd: {
    param: "rbd",
    on: "on",
    discard: {
      title: "Discard your changes to this RBD?", body: "The diagram has changes that aren't saved.",
      confirmLabel: "Discard the changes", cancelLabel: "Keep editing",
    },
  },
};

// Which pane the address asks for ({kind, id}: `id` the position; an RBD's also `rbd`, the
// diagram), or null. One at a time: a fit first, as it was the first. An RBD with no position
// (`on`) isn't one the Explorer can show beside a row.
export function paneFromQuery(params) {
  for (const [kind, p] of Object.entries(TABLE_PANES)) {
    const value = params?.get?.(p.param);
    if (!value) continue;
    if (!p.on) return { kind, id: value };
    const on = params.get(p.on);
    if (on) return { kind, id: on, [p.param]: value };
  }
  return null;
}

// Every pane's address parameters, for clearing them all.
export const PANE_PARAMS = Object.values(TABLE_PANES).flatMap((p) => (p.on ? [p.param, p.on] : [p.param]));

// Put the pane `kind` for `positionId` in the address `q` (URLSearchParams), any other pane's
// taken out; an RBD's `rbd`, the diagram.
export function setPaneQuery(q, kind, positionId, { rbd = null } = {}) {
  for (const k of PANE_PARAMS) q.delete(k);
  const p = TABLE_PANES[kind];
  if (p.on) {
    q.set(p.param, rbd);
    q.set(p.on, positionId);
  } else {
    q.set(p.param, positionId);
  }
  return q;
}
