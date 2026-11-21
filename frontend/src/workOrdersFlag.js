// Work orders can be turned off for a deployment (MAINTENANCE_WORK_ORDERS, from
// /api/config's maintenance_work_orders) while the rest of Maintenance keeps
// working: the tree, tasks and when they fall due, packages as plans,
// forecasts, spares, readings and failure reports. Off, nothing work-order
// shows: no Orders entry, no work-order lists or counts on Home, no "Raise work
// order" or close flows. Work is recorded as done on the task ("Record done")
// or the position or item ("Record what was done") instead. Work orders already
// recorded are kept, only hidden: turned back on, they show again.
// Pure (the tests import it); the hook is useWorkOrdersOn() in ConfigProvider.jsx.

// On unless the server says it's off (so nothing changes where it isn't set).
export const workOrdersOn = (config) => (config || {}).maintenance_work_orders !== false;

// The one line said wherever work orders would have been.
export const WORK_ORDERS_OFF_NOTE =
  "Work orders are turned off for this workspace: record what was done on the task or position instead.";
