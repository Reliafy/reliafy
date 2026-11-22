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
  // Which positions inside one back each other up (?redundancy=<position id>; Modelling and Missions).
  redundancy: {
    param: "redundancy",
    discard: {
      title: "Discard this redundancy set?", body: "The set you're marking isn't saved.",
      confirmLabel: "Discard it", cancelLabel: "Keep editing",
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
  // Adjust for conditions… on a model row (?adjust=<model row's link id>&on=<position id>): the model
  // with a hazard ratio, saved as a new model and put in the row's place (AdjustModelPanel.jsx).
  adjust: {
    param: "adjust",
    on: "on",
    discard: {
      title: "Discard this adjustment?", body: "The adjusted model isn't saved.",
      confirmLabel: "Discard it", cancelLabel: "Keep adjusting",
    },
  },
  // How a position runs (?plan=<position id>; Monitoring › Readings, where one opened from the Summary moves): its operating plan.
  plan: {
    param: "plan",
    discard: {
      title: "Discard this operating plan?", body: "The changes to how it runs aren't saved.",
      confirmLabel: "Discard it", cancelLabel: "Keep editing",
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
  // A model's Strategy on a position (?strategy=<model row's link id>&on=<position id>, and &how=<tool>):
  // its saved strategies and the strategy tools that fit (positionStrategy.js). Nothing to discard:
  // each tool saves on its own.
  strategy: {
    param: "strategy",
    on: "on",
    extra: { how: "how" },
    discard: {
      title: "Leave this strategy?", body: "The figures you've entered aren't saved.",
      confirmLabel: "Leave it", cancelLabel: "Stay",
    },
  },
  // A level's forecast (?forecast=<position id>; the Maintenance tab's Forecast… on a position): the
  // work, failures and costs to come there and everything inside it. Nothing to discard.
  forecast: {
    param: "forecast",
    discard: {
      title: "Close the forecast?", body: "Nothing is lost: it's worked out again when opened.",
      confirmLabel: "Close it", cancelLabel: "Keep it open",
    },
  },
  // Optimise… on a task (?optimise=<task id>&on=<its position id>; the Maintenance tab): how often to
  // do it, from its failure modes' life models. Each Use saves on its own: nothing to discard.
  optimise: {
    param: "optimise",
    on: "on",
    discard: {
      title: "Leave Optimise?", body: "The figures you've changed aren't used until you press Use.",
      confirmLabel: "Leave it", cancelLabel: "Stay",
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
    const more = Object.fromEntries(Object.entries(p.extra || {}).map(([name, k]) => [name, params.get(k)]).filter(([, v]) => v));
    if (on) return { kind, id: on, [p.param]: value, ...more };
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
export function setPaneQuery(q, kind, positionId, { rbd = null, from = null, how = null } = {}) {
  for (const k of PANE_PARAMS) q.delete(k);
  const p = TABLE_PANES[kind];
  if (p.on) {
    q.set(p.param, rbd);
    q.set(p.on, positionId);
  } else {
    q.set(p.param, positionId);
  }
  if (from && p.extra?.from) q.set(p.extra.from, from);
  if (how && p.extra?.how) q.set(p.extra.how, how);
  return q;
}
