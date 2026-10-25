// "Add the sample truck" on the Explorer: the sample delivery truck, with its
// RCM, copied into the workspace's own tree (POST /api/maintenance/sample-truck).
// Once: when a copy is there already, the server adds nothing and says which
// one, and the person is asked whether to add another copy or keep theirs.

export const SAMPLE_TRUCK_LABEL = "Add the sample truck";

// The question when a copy is already in the tree.
export function anotherCopyConfirm(name) {
  return {
    title: "The sample truck is already in your tree",
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
  const first = await add(false);
  if (first.added || !first.position) return first;
  if (!(await ask(anotherCopyConfirm(first.position.name)))) return first;
  return add(true);
}
