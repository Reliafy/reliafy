// The same task on identical positions (GET /api/maintenance/tasks/{id}/twins): after a task's
// interval changes, the page offers to give the same interval to the twins that still have
// another one (Pump B keeping 12,000 hours after Pump A went to 14,800). Pure functions, tested
// in taskTwins.test.js.

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;
const every = (interval, unit) => `${Number(interval).toLocaleString("en-AU")} ${unit || ""}`.trim();

// The twins whose interval or unit differs from the new one.
export function twinsToOffer(out, interval, unit) {
  return (out?.twins || []).filter((t) => !(Number(t.interval) === Number(interval) && (t.unit || "") === (unit || "")));
}

// The offer in words: "Pump B has “Replace the seal” every 12,000 hours. Give it 14,800 hours too?"
export function twinOfferText(name, twins, interval, unit) {
  if (!twins.length) return "";
  const where = twins.length === 1
    ? `${twins[0].position.name} has “${name}” every ${every(twins[0].interval, twins[0].unit)}.`
    : `${plural(twins.length, "identical position")} have “${name}” at another interval (${twins.map((t) => `${t.position.name}: ${every(t.interval, t.unit)}`).join("; ")}).`;
  return `${where} Give ${twins.length === 1 ? "it" : "them"} every ${every(interval, unit)} too?`;
}

// The PATCH bodies, one per twin.
export function twinWrites(twins, interval, unit) {
  return twins.map((t) => ({ id: t.id, body: { interval: Number(interval), unit } }));
}
