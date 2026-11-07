// A tiny invented graph and design for the Data model page's tests and
// screenshots: made-up labels, nothing from a real data model.
export const SCHEMA = {
  nodes: [
    { label: "Widget", count: 420, properties: { name: { type: "STRING", count: 420 }, size: { type: "INTEGER", count: 120 } } },
    { label: "Box", count: 58, properties: { name: { type: "STRING", count: 58 } } },
    { label: "Shelf", count: 12, properties: {} },
    { label: "Room", count: 3, properties: { floor: { type: "INTEGER", count: 3 } } },
  ],
  relationships: [
    { type: "INSIDE", count: 470, connects: [{ from: "Widget", to: "Box", count: 400 }, { from: "Box", to: "Room", count: 10 }] },
    { type: "PART_OF", count: 60, connects: [{ from: "Widget", to: "Widget", count: 60 }] },
    { type: "ON", count: 48, connects: [{ from: "Box", to: "Shelf", count: 48 }] },
    { type: "IN_ROOM", count: 12, connects: [{ from: "Shelf", to: "Room", count: 12 }] },
  ],
  freshness: { up_to_date: true },
};

export const DESIGN = {
  available: true,
  updated: "2026-10-20T08:00:00+00:00",
  nodes: [
    { id: "widget", label: "Widget", structure: "thing", definition: "A small thing that is kept somewhere." },
    { id: "box", label: "Box", structure: "container", definition: "Holds widgets." },
    { id: "room", label: "Room", structure: "place", definition: "Where boxes and shelves are." },
    { id: "crate", label: "Crate", structure: "container", definition: "A big box, for moving boxes together." },
  ],
  edges: [
    { from: "widget", type: "INSIDE", to: "box", status: "decided" },
    { from: "widget", type: "PART_OF", to: "widget", status: "decided" },
    { from: "box", type: "INSIDE", to: "room", status: "decided" },
    { from: "box", type: "INSIDE", to: "crate", status: "proposed", note: "Boxes travel in crates." },
    { from: "crate", type: "IN_ROOM", to: "room", status: "proposed" },
  ],
};

// Answer the page's three requests with these, as if this user had graph access.
export async function stubGraph(page, { schema = SCHEMA, design = DESIGN, schemaStatus = 200 } = {}) {
  const json = (body, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/maintenance/access", (r) => r.fulfill(json({ allowed: true, graph: true })));
  await page.route("**/api/maintenance/graph/schema", (r) => r.fulfill(schemaStatus === 200
    ? json(schema) : json({ detail: "unavailable" }, schemaStatus)));
  await page.route("**/api/maintenance/graph/design", (r) => r.fulfill(json(design)));
}
