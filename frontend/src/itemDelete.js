// The words of Delete… on an item's page (DeleteItemModal). The server's dry run says
// what goes: the item (retired: it leaves your lists, its history stays), a built
// item's tree with it, the item's own tasks. Plain words, the answer first.

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export const ITEM_DELETE_NOTE =
  "Nothing is erased: its fitments, work orders and readings stay in the history, and you can restore it from this page.";

// The lines of what goes with it ([] for nothing but the item).
export function itemDeleteLines(plan) {
  const out = [];
  const t = plan?.tree;
  if (t) {
    const inside = [t.positions ? plural(t.positions, "position") : null, t.tasks ? plural(t.tasks, "task") : null]
      .filter(Boolean).join(" and ");
    out.push(`Its tree, ${t.name}${inside ? `, with the ${inside} in it` : ""}.`);
    if (t.open_work_orders) out.push(`${plural(t.open_work_orders, "open work order")} on the tree, cancelled.`);
  }
  if (plan?.tasks) out.push(`${plural(plan.tasks, "task")} of its own, retired with it.`);
  return out;
}

export function itemDeleteButton(plan) {
  return plan?.tree ? "Delete the item and its tree" : "Delete the item";
}

// After a delete, on the page: "Deleted on 20 Nov 2026." with why when it was given.
export function deletedBanner(item, fmtDate = (d) => d) {
  if (!item?.retired) return "";
  const on = item.retired_on ? ` on ${fmtDate(item.retired_on)}` : "";
  return `${item.name} was deleted${on}. It isn't in your lists and can't be fitted; its history is kept.`;
}
