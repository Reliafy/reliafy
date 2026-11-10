// The Modelling tab's work that fills the Explorer's table area, the tree kept beside it, instead
// of a dialog (Derryn, 9 Nov 2026: "It shouldn't be a modal itself"; the parts count "should also
// be the same, where it fills up the table area"; an RBD should "fill up that table pane with the
// existing RBD builder"). Each has its own address, so a reload keeps it open, and its words for
// leaving it with something changed.
//
// A fit and a prediction are for a position (?fit=<position id>); an RBD is a diagram linked to a
// position (?rbd=<RBD id>&on=<position id>): `on` names the position whose row it opens beside.

export const TABLE_PANES = {
  // A fit can start from a model row as its prior (&prior=<row>: fitDialog.priorFrom). `extra`:
  // what the pane calls it, and its key in the address. The key is the pane's own word, never a
  // general one: a link from outside may carry ?from= or ?source=, and the Explorer clears a
  // pane's keys when another row is picked.
  fit: {
    param: "fit",
    extra: { from: "prior" },
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
  // A covariate model with some covariates fixed at a position (?bind=<source>:<ref>&on=<position>).
  bind: {
    param: "bind",
    on: "on",
    discard: {
      title: "Discard these covariates?", body: "What you've fixed at this position isn't saved.",
      confirmLabel: "Discard them", cancelLabel: "Keep fixing",
    },
  },
  // A mission on a position's RBD (?mission=<RBD id>:<mission id>&on=<position id>; the Missions tab).
  mission: {
    param: "mission",
    on: "on",
    discard: {
      title: "Discard your changes to this mission?", body: "The mission has changes that aren't saved.",
      confirmLabel: "Discard the changes", cancelLabel: "Keep editing",
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
    if (!p.on) {
      const more = Object.fromEntries(Object.entries(p.extra || {}).map(([name, k]) => [name, params.get(k)]).filter(([, v]) => v));
      return { kind, id: value, ...more };
    }
    const on = params.get(p.on);
    if (on) return { kind, id: on, [p.param]: value };
  }
  return null;
}

// Every pane's address parameters, for clearing them all.
export const PANE_PARAMS = [...new Set(Object.values(TABLE_PANES).flatMap((p) => [p.param, ...(p.on ? [p.on] : []), ...Object.values(p.extra || {})]))];

// Another row was picked: take out of the address `q` every pane open for a different position,
// with all its keys. A pane for `positionId` itself stays whole (a fit's prior, an RBD's diagram,
// a mission): its other keys aren't position ids, so they can't be compared with the row picked.
export function keepPaneFor(q, positionId) {
  for (const p of Object.values(TABLE_PANES)) {
    if (!q.get(p.param) || q.get(p.on || p.param) === positionId) continue;
    for (const k of [p.param, ...(p.on ? [p.on] : []), ...Object.values(p.extra || {})]) q.delete(k);
  }
  if (!paneFromQuery(q)) for (const k of PANE_PARAMS) q.delete(k);
  return q;
}

// Put the pane `kind` for `positionId` in the address `q` (URLSearchParams), any other pane's
// taken out; an RBD's `rbd`, the diagram; a fit's `from`, the model row it starts from (&prior=).
export function setPaneQuery(q, kind, positionId, { rbd = null, from = null } = {}) {
  for (const k of PANE_PARAMS) q.delete(k);
  const p = TABLE_PANES[kind];
  if (p.on) {
    q.set(p.param, rbd);
    q.set(p.on, positionId);
  } else {
    q.set(p.param, positionId);
  }
  if (from && p.extra?.from) q.set(p.extra.from, from);
  return q;
}
