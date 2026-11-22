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

// The task's details follow the design system: the task's name is the panel's title, the fields are
// the shared Field and controls in Sections, and Save, Cancel and Retire… sit in the shared footer.
test("the task panel is built from the shared title, Field, Section and footer", () => {
  const task = read("components/MaintenanceTask.jsx");
  const side = read("components/TaskTreeTable.jsx");
  assert.doesNotMatch(side, /"Maintenance task" : "Add a task"/); // no generic h2 over the task's name
  assert.match(task, /<h2 className="rw-panel-title"[^>]*>\{title\}<\/h2>/);
  assert.doesNotMatch(task, /<h3 className="pk-view-name">\{adding/);
  assert.match(task, /import Field from "\.\/ui\/Field\.jsx"/);
  assert.doesNotMatch(task, /<fieldset className="mt-(how|restore|modes)"/);
  assert.doesNotMatch(task, /type="checkbox"/);
  assert.match(task, /className="rw-panel-acts mt-acts"/);
  assert.match(task, /className="ghost rw-del"[^\n]*>Retire…</);
  assert.match(task, /<LoadFailed /);
  assert.match(task, /<PlaceholderRows shape="fields"/);
  assert.match(task, /\$\{money\(lsaCost\)\} from its LSA/);
});

test("the task panel's styles use tokens: no hex, rgba or raw px sizes", () => {
  for (const f of ["components/LsaPanel.css", "components/HowOften.css", "components/RbdTaskUses.css"]) {
    const css = read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/@media[^{]*\{/g, "");
    assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b/i, f);
    assert.doesNotMatch(css, /rgba?\(/, f);
    assert.doesNotMatch(css, /\b(?!1px\b|0px\b)\d+px\b/, f); // hairlines only
    assert.doesNotMatch(css, /\d(\.\d+)?em\b/, f);
  }
});
