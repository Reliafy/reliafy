import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// The Maintenance tab's task details use the Explorer's shared "details across the table" behaviour
// (the one Models and Measurements use): a double-click or Enter expands, Back and Esc return.
const SRC = new URL("./", import.meta.url);
const read = (rel) => readFileSync(new URL(rel, SRC), "utf8");

test("opening a task row (double-click, Enter, Open…) expands the details across the table on a wide screen", () => {
  const src = read("views/AssetExplorer.jsx");
  const open = src.slice(src.indexOf("const openTaskRow"), src.indexOf("const openForecast"));
  assert.match(open, /if \(!phone\) setExpanded\(true\)/);
  assert.match(src, /onOpen: \(key\) => openTaskRow\(/); // the table's double-click
  assert.match(src, /if \(isTaskRow\(r\)\) return openTaskRow\(r\)/); // Enter
});

test("the task side offers Back to table and Esc returns before it closes", () => {
  const side = read("components/TaskTreeTable.jsx");
  assert.match(side, /expanded && onCollapse\) onCollapse\(\); else onClose\(\)/);
  assert.match(side, /aria-label="Back to table"/);
  assert.match(read("views/AssetExplorer.jsx"), /<TaskSide [^>]*\n\s*expanded=\{wideDetails\} onExpand=\{expandDetails\} onCollapse=\{collapseDetails\}/);
});
