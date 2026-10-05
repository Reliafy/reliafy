// A stress's or covariate's name with its optional unit (#265):
// "Temperature (K)" — left as it is when the label already names the unit
// ("Voltage (kV)") or there is no unit.
export function withUnit(label, unit) {
  const name = String(label ?? "");
  const u = String(unit ?? "").trim();
  if (!u || name.includes(`(${u})`) || name.trim() === u) return name;
  return `${name} (${u})`;
}

export function stressName(s) {
  return withUnit(s?.label || s?.column || "", s?.unit);
}
