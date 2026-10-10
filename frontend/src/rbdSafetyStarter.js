// The safety function starter (#298): a low-demand safety instrumented
// function of the usual shape — two pressure transmitters voting 1oo2 (with a
// common-cause group), a logic solver and a shutdown valve — each failing
// dangerously undetected at a constant rate (λDU) and proof-tested yearly,
// repaired at once when a test finds it failed. It opens unsaved in safety
// mode, with a SIL 2 target, ready to calculate; the figures are typical
// orders of magnitude to replace with the loop's own.

const EDGE = { type: "smoothstep", markerEnd: { type: "arrowclosed", width: 18, height: 18 } };
const SIDES = { sourcePosition: "right", targetPosition: "left" };
const YEAR = 8760; // hours: the proof-test interval

const lambdaDU = (rate) => ({
  source: "params",
  distribution: "Exponential",
  distribution_id: "exponential",
  params: [{ name: "failure_rate", value: rate }],
});

function element(id, label, rate, x, y) {
  return {
    id,
    type: "component",
    position: { x, y },
    ...SIDES,
    data: { label, model: lambdaDU(rate), instant_repair: true, inspection: { interval: YEAR } },
  };
}

export const SAFETY_STARTER_NAME = "Safety function (starter)";

export function safetyStarterGraph() {
  const nodes = [
    { id: "input", type: "input", data: { label: "Input" }, position: { x: 0, y: 0 } },
    element("c1", "Pressure transmitter A", 3e-7, 240, -90),
    element("c2", "Pressure transmitter B", 3e-7, 240, 90),
    element("c3", "Logic solver", 1e-8, 520, 0),
    element("c4", "Shutdown valve", 1e-6, 800, 0),
    { id: "output", type: "output", data: { label: "Output" }, position: { x: 1080, y: 0 } },
  ];
  const links = [["input", "c1"], ["input", "c2"], ["c1", "c3"], ["c2", "c3"], ["c3", "c4"], ["c4", "output"]];
  return {
    unit: "Hours",
    repairable: true,
    safety_function: true,
    target_sil: 2,
    nodes,
    edges: links.map(([source, target]) => ({ id: `e-${source}-${target}`, source, target, ...EDGE })),
    ccf_groups: [{ id: "ccf-transmitters", members: ["c1", "c2"], beta: 0.05 }],
  };
}

// What the builder opens: the shape an imported diagram has, marked as the
// starter so its note says so.
export function safetyStarter() {
  return { name: SAFETY_STARTER_NAME, graph: safetyStarterGraph(), starter: "safety" };
}
