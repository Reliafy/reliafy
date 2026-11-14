// Merging one asset into another (Derryn, 14 Nov 2026: "Alternately, they can merge one asset into
// another"): the Explorer is always one asset, so the way to see two together is to make one part of
// the other. And the way back: Make this its own asset.
//
// No new kind of change: a merge is the move the tree already has (a location's parent, a position's
// parent or place), so everything below the merged asset keeps its history, readings, tasks, RCM and
// fitments. An asset is a top place (a location with nothing above it) or a top position at no place.
//   a place     goes inside a location of the other asset (PATCH /locations/:id {parent_id})
//   a position  goes inside a position of it (PATCH /positions/:id {parent_id}), or at one of its
//               locations (PATCH /positions/:id {location_id})
// Making a row its own asset clears the same: a location's parent; a position's parent and own place.
//
// Pure functions (no React), tested in assetMerge.test.js.

import { pointMoveChoices } from "./measuringPoint.js";

// What the asset open is ("place" or "unit": a top position), from the scoped tree's scope; null for
// anything that can't be merged (a product's design, nothing read yet).
export function mergeSourceKind(scope) {
  if (scope?.kind === "place") return "place";
  if (scope?.kind === "unit") return "unit";
  return null;
}

// The assets it can join (the Assets list's places, not itself), matching the search, A to Z.
export function mergeTargets(places, sourceId, query = "") {
  const q = String(query || "").trim().toLowerCase();
  return (places || [])
    .filter((p) => p && p.id && p.id !== sourceId)
    .filter((p) => !q || [p.name, p.description].some((t) => String(t || "").toLowerCase().includes(q)))
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), "en", { sensitivity: "base", numeric: true }));
}

// Where in the target's tree it can go: the target's locations (a place goes only inside a location),
// and for a position its positions too. [{id, kind: "loc" | "pos", name, tag, depth, path}].
// `tree`: the target asset's own tree read (GET /tree?within=<target>).
export function mergeSpots(tree, sourceKind, query = "") {
  if (!tree || !sourceKind) return { rows: [], more: false };
  const locs = pointMoveChoices((tree.locations || []).map((l) => ({ id: l.id, name: l.name, parent_id: l.parent_id ?? null })), query);
  const rows = locs.rows.map((r) => ({ ...r, kind: "loc" }));
  let more = locs.more;
  if (sourceKind === "unit") {
    const free = (tree.positions || []).filter((p) => !p.carried_by && !p.retired);
    const pos = pointMoveChoices(free, query);
    rows.push(...pos.rows.map((r) => ({ ...r, kind: "pos" })));
    more = more || pos.more;
  }
  return { rows, more };
}

// What comes along: the positions, items and locations inside the asset open (not itself).
// `data`: the Explorer's scoped tree.
export function mergeCounts(data, sourceKind) {
  const positions = data?.positions || [];
  const locations = data?.locations || [];
  return {
    positions: Math.max(0, positions.length - (sourceKind === "unit" ? 1 : 0)),
    items: positions.filter((p) => p.fitted || p.item).length + (data?.spares || []).length,
    locations: Math.max(0, locations.length - (sourceKind === "place" ? 1 : 0)),
  };
}

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// The preview, in words: "Pump station 2 and its 14 positions, 9 items and 3 locations will become part
// of Site A, inside Pump hall." `spot`: {id, kind, name} in the target (its top place: just "part of").
export function mergeSentence(sourceName, counts, target, spot) {
  const parts = [counts?.positions && plural(counts.positions, "position"), counts?.items && plural(counts.items, "item"),
    counts?.locations && plural(counts.locations, "location")].filter(Boolean);
  const along = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
  const who = `${sourceName || "(no name)"}${along ? ` and its ${along}` : ""}`;
  const where = !spot || spot.id === target?.id ? "" : `, ${spot.kind === "pos" ? "inside" : "at"} ${spot.name || "(no name)"}`;
  return `${who} will become part of ${target?.name || "(no name)"}${where}.`;
}

// The change a merge makes: {kind: "location" | "position", id, body}. null when the spot can't take it
// (a place goes only inside a location).
export function mergeChange(sourceKind, sourceId, spot) {
  if (!spot || !sourceId) return null;
  if (sourceKind === "place") return spot.kind === "loc" ? { kind: "location", id: sourceId, body: { parent_id: spot.id } } : null;
  if (sourceKind === "unit") {
    return { kind: "position", id: sourceId, body: spot.kind === "pos" ? { parent_id: spot.id } : { location_id: spot.id } };
  }
  return null;
}

// The change Make this its own asset makes on a row inside an asset: a location leaves its parent; a
// position leaves its parent and its own place (it's then a top position at no place: an asset of its
// own). null for anything else.
export function separateChange(row) {
  if (!row?.key) return null;
  if (row.type === "loc") return { kind: "location", id: row.key, body: { parent_id: null } };
  if (row.type !== "pos") return null;
  const ref = row.ref || {};
  const body = {};
  if (ref.parent_id) body.parent_id = null;
  if (ref.location_id || (ref.location && !ref.location.inherited)) body.location_id = null;
  return Object.keys(body).length ? { kind: "position", id: row.key, body } : null;
}

// The confirm for Make this its own asset… (ConfirmProvider: title, body, the button saying the action).
// `row`: the tree row; `assetName`: the asset it's leaving.
export function separateConfirm(row, assetName) {
  const name = row?.ref?.name || "(no name)";
  const from = assetName || "this asset";
  const pos = row?.type === "pos";
  return {
    title: `Make ${name} its own asset?`,
    body: [
      `${name} and everything inside it leave ${from} and become an asset of their own, with their history, readings, tasks, RCM and fitments.`,
      pos ? "Cause-and-effect links between it and the rest of the tree are removed. It's listed under Not at a place yet on Assets until you give it a place." : "",
      `To put it back, use Merge into another asset… on it.`,
    ].filter(Boolean).join(" "),
    confirmLabel: "Make it its own asset",
    destructive: false,
  };
}
