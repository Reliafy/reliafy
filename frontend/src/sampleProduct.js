// The sample product, a survey quadcopter's design with three items built from it
// and their reports (POST /api/maintenance/sample-product): the one sample for the
// RCM and FME(C)A tabs. "Add the sample UAV product" on Products adds it; "Open the
// sample UAV product" on the Explorer opens it on its structure's RCM or FME(C)A tab
// (adding it first when there's none). Once: when a copy is there already, the
// server adds nothing and says which one, and Products asks whether to add another
// copy or keep the one there. "Open the sample quadcopter" on Assets opens the
// first item built from it (an operated thing, on its own tree), adding the sample
// first when there's none.
import { itemTreePath, productPath } from "./products.js";

export const SAMPLE_PRODUCT_LABEL = "Add the sample UAV product";
export const OPEN_SAMPLE_PRODUCT_LABEL = "Open the sample UAV product";
export const OPEN_SAMPLE_UNITS_LABEL = "Open the sample quadcopter";

export const SAMPLES = {
  product: { label: SAMPLE_PRODUCT_LABEL, what: "sample product", where: "workspace", added: "Added the sample UAV product." },
};

// The question when a copy is already there.
export function anotherCopyConfirm(name, what = "sample product", where = "workspace") {
  return {
    title: `The ${what} is already in your ${where}`,
    body: `It's there as “${name}”. Add another copy to start again from the sample, or keep the one you have.`,
    confirmLabel: "Add another copy",
    cancelLabel: "Keep the one I have",
    destructive: false,
  };
}

// The product the server's answer names (added, or the copy already there).
export const sampleProductId = (r) => r?.product?.id || r?.position?.id;

// The tab the Explorer's sample opens the product on: the FME(C)A when that's the
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

// Assets' sample: the first item built from the sample product, on its tree (the
// Explorer scoped to it). add(again) posts the sample (once: with a copy there the
// server answers with it and adds nothing); listItems(id) reads the items built
// from a product (the answer carries them only when it added the sample). With no
// item built, the product's own page.
export async function sampleUnitsPath(add, listItems) {
  const r = await add(false);
  const id = sampleProductId(r);
  const items = r.items?.length ? r.items : id ? (await listItems(id)).items || [] : [];
  const top = items.find((it) => it.top_position_id)?.top_position_id;
  return top ? itemTreePath(top) : productPath(id);
}
