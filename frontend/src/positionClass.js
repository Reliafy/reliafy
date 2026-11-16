// A position's class (Nov 2026). A position built from a product's design is of
// its design position's class: shown by the product and the path down to it
// ("UAV › Propulsion › Motor 1", following renames), and named to the server by
// a stable key ("design:<id>"). Any other position's class is its free text.
// Tree rows carry `class_key` and `class_label` only for a design class; a
// position read carries `class` ({position_class, class_key, design_position_id,
// product}); the class reads carry `class_key` beside `position_class`.

// The key to group by and to pass to the class reads ("" with no class).
export function classKey(ref) {
  return ref?.class_key || ref?.class?.class_key || (ref?.position_class || "").trim();
}

// The class as shown ("" with none).
export function classLabel(ref) {
  return ref?.class_label || ref?.class?.position_class || (ref?.position_class || "").trim();
}

// Whether the class comes from a product's design (then the free-text class isn't offered).
export function isDesignClass(ref) {
  return classKey(ref).startsWith("design:");
}

const many = (n, one, more) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : more}`;

// "Built as 2 positions": the heading over a design position's built positions.
export function builtAsTitle(n) {
  return n ? `Built as ${many(n, "position", "positions")}` : "Not built yet";
}

// "Carried as 2 locations": the heading over a design location's copies on built units.
export function carriedAsTitle(n) {
  return n ? `Carried as ${many(n, "location", "locations")}` : "Not carried yet";
}

// A tree row's class fields, to pass on with a position ({id, name, ...}) to the panes
// that read its class (fitting a class model, a strategy's costs).
export function classFields(ref) {
  return {
    position_class: ref?.position_class || "",
    ...(ref?.class_key ? { class_key: ref.class_key, class_label: ref.class_label || "" } : {}),
  };
}
