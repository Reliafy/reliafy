import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addWorkspaceId, countsText, dataLine, entryAnchor, entryPath, entryTags, filterEntries, groupLibraries, libraryMatches,
  libraryPath, modelBasis, modelHeadline, publicLibraryId, sharingProblems, showsPublicLibrary, usedLinks, visibilityBody,
} from "./libraries.js";

test("a library's address, and which addresses the public page answers", () => {
  assert.equal(libraryPath("abc 1"), "/libraries/abc%201");
  assert.equal(publicLibraryId("/libraries/abc123"), "abc123");
  assert.equal(publicLibraryId("/libraries/nswc-11/"), "nswc-11");
  assert.equal(publicLibraryId("/libraries/data"), null);
  assert.equal(publicLibraryId("/libraries/models"), null);
  assert.equal(publicLibraryId("/libraries"), null);
  assert.equal(publicLibraryId("/libraries/nrc-inl-2020/mov-fto"), null);
  assert.equal(publicLibraryId("/data/abc"), null);
});

test("signed out, or Preview as public, shows the standalone page; signed in shows the app", () => {
  assert.equal(showsPublicLibrary("/libraries/abc", "", false), true);
  assert.equal(showsPublicLibrary("/libraries/abc", "", true), false);
  assert.equal(showsPublicLibrary("/libraries/abc", "?as=public", true), true);
  assert.equal(showsPublicLibrary("/libraries/data", "?as=public", false), false);
  assert.equal(showsPublicLibrary("/models/m/1", "", false), false);
});

test("the cards' counts and the three sections", () => {
  assert.equal(countsText({ counts: { data: 1, model: 2, total: 3 } }), "1 dataset · 2 models");
  assert.equal(countsText({ counts: {} }), "0 datasets · 0 models");
  assert.equal(countsText({ builtin: true, counts: { model: 236, total: 236 } }), "236 records");
  const g = groupLibraries([{ id: "a", relation: "yours" }, { id: "b", relation: "shared" }, { id: "c", relation: "public" },
    { id: "d", relation: "public", builtin: true }]);
  assert.deepEqual(g.yours.map((c) => c.id), ["a"]);
  assert.deepEqual(g.shared.map((c) => c.id), ["b"]);
  assert.deepEqual(g.public.map((c) => c.id), ["c", "d"]);
  assert.ok(libraryMatches({ name: "Pumps", description: "Plant A" }, "plant"));
  assert.ok(libraryMatches({ name: "Pumps", citation: "OREGON 2019" }, "oregon"));
  assert.ok(!libraryMatches({ name: "Pumps" }, "valves"));
  assert.ok(libraryMatches({ name: "Pumps" }, "  "));
});

const DATA = { id: "L:1", type: "data", name: "Bearing lives", tags: ["Non-repairable"],
  data: { n_rows: 20, reading_summary: "x = Age (hours) · c = Status" } };
const FITTED = { id: "L:2", type: "model", name: "Bearing Weibull", tags: ["Non-repairable"],
  model: { distribution: "Weibull", unit: "hours", headline: { text: "B10 1,230 hours (90% lower bound 980 hours)" },
    fitted_on: { entry_id: "L:1", name: "Bearing lives" }, basis_text: "Fitted to data (12 failures, 8 running)" } };
const PARAMS = { id: "L:3", type: "model", name: "Valve rate", tags: ["Non-repairable"],
  model: { distribution: "Exponential", unit: "hours", headline: null, fitted_on: null, basis_text: "From parameters" } };
const REPAIRABLE = { id: "L:4", type: "model", name: "Pump repairs", tags: ["Repairable"],
  model: { distribution: "Crow-AMSAA", unit: "days", headline: null, fitted_on: null, basis_text: "From MIL-HDBK-217F" } };
const ALL = [DATA, FITTED, PARAMS, REPAIRABLE];

test("entries filter by kind, tag and words", () => {
  assert.deepEqual(entryTags(ALL), ["Non-repairable", "Repairable"]);
  assert.deepEqual(filterEntries(ALL, { kind: "data" }).map((e) => e.id), ["L:1"]);
  assert.deepEqual(filterEntries(ALL, { kind: "model", tag: "Non-repairable" }).map((e) => e.id), ["L:2", "L:3"]);
  assert.deepEqual(filterEntries(ALL, { q: "b10" }).map((e) => e.id), ["L:2"]);
  assert.deepEqual(filterEntries(ALL, { q: "217f" }).map((e) => e.id), ["L:4"]);
  assert.deepEqual(filterEntries(ALL, { q: "age (hours)" }).map((e) => e.id), ["L:1"]);
  assert.equal(filterEntries(ALL).length, 4);
});

test("a model's headline, and where it came from: fitted on a dataset in the library, or its basis in words", () => {
  assert.equal(modelHeadline(FITTED.model), "B10 1,230 hours (90% lower bound 980 hours)");
  assert.equal(modelHeadline(PARAMS.model), "Exponential, in hours");
  assert.deepEqual(modelBasis(FITTED.model), { fittedOn: { entry_id: "L:1", name: "Bearing lives" } });
  // Not fitted on data: its basis, never a gap or a warning.
  assert.deepEqual(modelBasis(PARAMS.model), { text: "From parameters" });
  assert.deepEqual(modelBasis(REPAIRABLE.model), { text: "From MIL-HDBK-217F" });
  assert.equal(dataLine(DATA.data), "x = Age (hours) · c = Status · 20 rows");
  assert.equal(dataLine({ n_rows: 1 }), "1 row");
  assert.equal(entryAnchor("abc:12f"), "entry-abc-12f");
  assert.equal(entryPath("abc", "abc:12f"), "/libraries/abc#entry-abc-12f");
});

test("sharing: what's missing before saving, and the body sent", () => {
  assert.deepEqual(sharingProblems({ visibility: "private" }), []);
  assert.deepEqual(sharingProblems({ visibility: "workspaces", workspaces: [] }), ["Add at least one workspace ID."]);
  assert.deepEqual(sharingProblems({ visibility: "workspaces", workspaces: ["t1"] }), []);
  assert.equal(sharingProblems({ visibility: "public" }).length, 3);
  assert.deepEqual(sharingProblems({ visibility: "public", licence: "cc-by-4.0", citation: "Smith 2020", rights: true }), []);
  assert.deepEqual(addWorkspaceId(["a"], " b "), ["a", "b"]);
  assert.deepEqual(addWorkspaceId(["a"], "a"), ["a"]);
  assert.deepEqual(addWorkspaceId(["a"], "  "), ["a"]);
  assert.deepEqual(visibilityBody({ visibility: "private", workspaces: ["x"] }), { visibility: "private" });
  assert.deepEqual(visibilityBody({ visibility: "workspaces", workspaces: ["x"] }), { visibility: "workspaces", workspaces: ["x"] });
  assert.deepEqual(visibilityBody({ visibility: "public", licence: "cc0", source: " NRC ", citation: " Smith ", rights: true }),
    { visibility: "public", licence: "cc0", source: "NRC", citation: "Smith", rights_confirmed: true });
});

test("after Use: links to the copies made", () => {
  assert.deepEqual(usedLinks({ model: { name: "M", url: "/models/m/1" }, dataset: { name: "D", url: "/data/2", reused: true } }), [
    { label: "M", to: "/models/m/1", what: "model" },
    { label: "D", to: "/data/2", what: "dataset", reused: true },
  ]);
  assert.deepEqual(usedLinks({ dataset: null, model: null }), []);
});
