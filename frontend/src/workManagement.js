// Work management can be turned off for a deployment (WORK_MANAGEMENT, from
// /api/config's work_management; maintenance_work_orders is its earlier name).
// Off, Reliafy is reliability software: the tree, RCM and its tasks, maintenance
// plans as hypothetical plans (tasks, intervals, packages and shutdowns, each task
// with an optional "last done" the forecasts count from), forecasts, spares,
// readings, history and failure reports (FRACAS, in full). Hidden: work orders
// and everything about executing work (raising, closing, labour, parts used),
// package visits, the to-do lists of what's due or overdue, and the technician's
// view. Nothing is deleted: turned back on, the work orders show again.
// Pure (the tests import it); the hook is useWorkManagementOn() in ConfigProvider.jsx.

// On unless the server says it's off (so nothing changes where it isn't set).
export function workManagementOn(config) {
  const c = config || {};
  if (c.work_management === false) return false;
  if (c.work_management === true) return true;
  return c.maintenance_work_orders !== false;
}

// Words that change with it: a task's next date is "due" in a work plan and
// "planned" in a hypothetical one.
export function planWords(on = true) {
  return on
    ? { next: "Next due", nextShort: "Due" }
    : { next: "Next planned", nextShort: "Planned" };
}

// The one line said where a task's last done is set with it off.
export const LAST_DONE_NOTE =
  "Last done is a plan input: the forecasts count each task from it. Leave it blank and they count from when "
  + "the task was added, or from a new item fitted since.";
