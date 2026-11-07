// "Add the sample truck" on the Explorer: the sample delivery truck, with its
// RCM (POST /api/maintenance/sample-truck), copied into the workspace's own
// tree. Once: when a copy is there already, the server adds nothing and says
// which one, and the person is asked whether to add another copy or keep theirs.

export const SAMPLE_TRUCK_LABEL = "Add the sample truck";
// On Products: a quadcopter's design, three items built from it and their reports
// (POST /api/maintenance/sample-product). It is the one quadcopter example: the
// Explorer's FME(C)A sample opens it (adding it first when there's none).
export const SAMPLE_PRODUCT_LABEL = "Add the sample UAV product";
export const OPEN_SAMPLE_PRODUCT_LABEL = "Open the sample UAV product";

export const SAMPLES = {
  truck: { label: SAMPLE_TRUCK_LABEL, what: "sample truck", tab: "rcm", added: "Added the sample truck." },
  product: { label: SAMPLE_PRODUCT_LABEL, what: "sample product", where: "workspace", added: "Added the sample UAV product." },
};

// The question when a copy is already in the tree.
export function anotherCopyConfirm(name, what = "sample truck", where = "tree") {
  return {
    title: `The ${what} is already in your ${where}`,
    body: `It's there as “${name}”. Add another copy to start again from the sample, or keep the one you have.`,
    confirmLabel: "Add another copy",
    cancelLabel: "Keep the one I have",
    destructive: false,
  };
}

// add(again) posts it; ask(opts) is the app's confirm. Resolves to the server's
// answer: { added, position: { id, name }, message }. With a copy there and the
// person keeping it, added is false and position is that copy.
export async function addSampleTruck(add, ask) {
  return addSample(add, ask, "truck");
}
// The product the server's answer names (added, or the copy already there).
export const sampleProductId = (r) => r?.product?.id || r?.position?.id;
export async function addSample(add, ask, kind = "truck") {
  const first = await add(false);
  if (first.added || !first.position) return first;
  if (!(await ask(anotherCopyConfirm(first.position.name, SAMPLES[kind]?.what, SAMPLES[kind]?.where)))) return first;
  return add(true);
}
