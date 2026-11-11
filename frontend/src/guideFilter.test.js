import { test } from "node:test";
import assert from "node:assert/strict";
import { filterGuideGroups } from "./guideFilter.js";

const GROUPS = [
  { category: "Getting started", items: [
    { slug: "first", title: "Fit your first non-repairable model from a CSV",
      task: "How do I turn a spreadsheet of failure times into a fitted reliability model?" },
    { slug: "share", title: "Share models and diagrams with other people",
      task: "How do I show a colleague my analysis, or work on it as a team?" },
  ] },
  { category: "Life data modelling", items: [
    { slug: "censored", title: "Handle censored data (units that haven't failed)",
      task: "How do I include units that are still running, or failed between inspections?" },
    { slug: "no-task", title: "Read B-lives and confidence bounds" },
  ] },
];

const slugs = (groups) => groups.map((g) => g.items.map((i) => i.slug));

test("guides filter: nothing typed keeps every group and guide", () => {
  assert.equal(filterGuideGroups(GROUPS, ""), GROUPS);
  assert.equal(filterGuideGroups(GROUPS, "   "), GROUPS);
  assert.equal(filterGuideGroups(GROUPS), GROUPS);
});

test("guides filter: matches the title or the task, whatever the case", () => {
  assert.deepEqual(slugs(filterGuideGroups(GROUPS, "CENSORED")), [["censored"]]);
  // "colleague" is only in the task line.
  assert.deepEqual(slugs(filterGuideGroups(GROUPS, "colleague")), [["share"]]);
  // In both groups: each keeps its own heading.
  const both = filterGuideGroups(GROUPS, "fail");
  assert.deepEqual(both.map((g) => g.category), ["Getting started", "Life data modelling"]);
  assert.deepEqual(slugs(both), [["first"], ["censored"]]);
});

test("guides filter: every word must be there, in any order, across title and task", () => {
  assert.deepEqual(slugs(filterGuideGroups(GROUPS, "csv fit")), [["first"]]);
  assert.deepEqual(slugs(filterGuideGroups(GROUPS, "csv spreadsheet")), [["first"]]);
  assert.deepEqual(slugs(filterGuideGroups(GROUPS, "csv colleague")), []);
});

test("guides filter: no match leaves no groups, and a guide with no task still matches by title", () => {
  assert.deepEqual(filterGuideGroups(GROUPS, "zzz"), []);
  assert.deepEqual(slugs(filterGuideGroups(GROUPS, "b-lives")), [["no-task"]]);
  // The groups given are not changed.
  assert.equal(GROUPS[0].items.length, 2);
});
