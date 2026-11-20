// The options of the shared position picker (PositionPicker, built on Select with its
// search box): each position by name (with its tag, "P-101 · Filter pump") and, under
// it, the way down to it ("Riverside pump station › Pump skid"), so a long tree is found
// by typing a name, tag or the system it's in, and two "Pump 1"s can be told apart.
// `positions`: [{id, name, depth, tag?, path?}] (MaintenanceParts' flatten). `emptyLabel`:
// the option for none first ("None (top level)"), or null for no such option.
export function positionOptions(positions = [], emptyLabel = null) {
  const out = emptyLabel != null ? [{ value: "", label: emptyLabel }] : [];
  for (const p of positions || []) {
    const label = p.tag && p.tag !== p.name ? `${p.tag} · ${p.name}` : p.name;
    const hint = (p.path || []).join(" › ");
    out.push(hint ? { value: p.id, label, hint } : { value: p.id, label });
  }
  return out;
}
