// The Survey quadcopter, a ready-made product: a quadcopter's design with three
// items built from it and their reports (POST /api/maintenance/sample-product), the
// one worked example for the RCM and FME(C)A tabs. Once added it is a product like
// any other: nothing on it says where it came from. "Add the Survey quadcopter" on
// Products adds it; "Open the Survey quadcopter" on the Explorer opens it on its
// structure's RCM or FME(C)A tab (adding it first when there's none). Once: when a
// copy is there already, the server adds nothing and says which one, and Products
// asks whether to add another copy or keep the one there. "Open a Survey
// quadcopter" on Assets opens the first item built from it (an operated thing, on
// its own tree), adding the product first when there's none.
import { itemTreePath, productPath } from "./products.js";

export const SAMPLE_PRODUCT_LABEL = "Add the Survey quadcopter";
export const OPEN_SAMPLE_PRODUCT_LABEL = "Open the Survey quadcopter";
export const OPEN_SAMPLE_UNITS_LABEL = "Open a Survey quadcopter";

export const SAMPLES = {
  product: { label: SAMPLE_PRODUCT_LABEL, what: "Survey quadcopter", where: "workspace", added: "Added the Survey quadcopter." },
};

// Is a copy of it among the Products page's rows (as added, or since made the
// person's own)? With one there the page's header stops offering it; the "…"
// menu still does.
export const hasCopy = (rows) => (rows || []).some((p) => !!p?.template);

// The question when a copy is already there.
export function anotherCopyConfirm(name, what = "Survey quadcopter", where = "workspace") {
  return {
    title: `Add another ${what}?`,
    body: `${what} is already in your ${where} as “${name}”. Add another copy, or keep the one you have.`,
    confirmLabel: "Add another copy",
    cancelLabel: "Keep the one I have",
    destructive: false,
  };
}

// What's said on the product's page once it's added: that it was, and any of its
// life models or analyses the workspace had no room for (those stay linked to the
// shared library's records; the server says which). Nothing with no copy added.
export function addedNote(r, kind = "product") {
  if (!r?.added) return null;
  const kept = (r.kept_note || "").trim();
  return { text: [SAMPLES[kind].added, kept].filter(Boolean).join(" "), fade: !kept };
}

// The product the server's answer names (added, or the copy already there).
export const sampleProductId = (r) => r?.product?.id || r?.position?.id;

// The tab the Explorer opens the product on: the FME(C)A when that's the
// tab in view, the RCM otherwise.
export const sampleProductView = (tab) => (tab === "fmea" ? "fmea" : "rcm");

// add(again) posts it; ask(opts) is the app's confirm. Resolves to the server's
// answer: { added, product, position: { id, name }, message }. With a copy there
// and the person keeping it, added is false and position is that copy.
export async function addSample(add, ask, kind = "product") {
  const first = await add(false);
  if (first.added || !first.position) return first;
  if (!(await ask(anotherCopyConfirm(first.position.name, SAMPLES[kind]?.what, SAMPLES[kind]?.where)))) return first;
  return add(true);
}

// Assets' one: the first item built from the product, on its tree (the Explorer
// scoped to it). add(again) posts the product (once: with a copy there the server
// answers with it and adds nothing); listItems(id) reads the items built from a
// product (the answer carries them only when it added the product). With no item
// built, the product's own page.
export async function sampleUnitsPath(add, listItems) {
  const r = await add(false);
  const id = sampleProductId(r);
  const items = r.items?.length ? r.items : id ? (await listItems(id)).items || [] : [];
  const top = items.find((it) => it.top_position_id)?.top_position_id;
  return top ? itemTreePath(top) : productPath(id);
}
