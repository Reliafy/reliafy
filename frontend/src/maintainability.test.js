import test from "node:test";
import assert from "node:assert/strict";
import {
  ELEMENTS, availabilityText, emptyForm, emptyLine, formProblem, fromInputs, hasElements, isBlank, lineMttr,
  linesFromProduct, parsePartsList, plainHeadline, toInputs, usedElements, weightsText,
} from "./maintainability.js";

const line = (over = {}) => ({ ...emptyLine(), ...over, elements: { ...emptyLine().elements, ...(over.elements || {}) } });

test("a line's repair time is the sum of its elements, else its MTTR", () => {
  assert.equal(lineMttr(line({ elements: { isolation: "10", replace: "15.5" } })), 25.5);
  assert.equal(lineMttr(line({ mttr: "1,200" })), 1200);
  assert.equal(lineMttr(line()), null);
  assert.ok(Number.isNaN(lineMttr(line({ elements: { access: "ten" } }))));
  assert.ok(Number.isNaN(lineMttr(line({ mttr: "-1" }))));
  assert.ok(hasElements(line({ elements: { checkout: "0" } })));
  assert.ok(!hasElements(line({ mttr: "3" })));
});

test("the form says what to fix before it can compute", () => {
  const form = emptyForm();
  assert.match(formProblem(form), /Add a line/);
  form.lines = [line({ quantity: "2", mttr: "3" })];
  assert.match(formProblem(form), /Line 1 needs a name/);
  form.lines = [line({ name: "Motor" })];
  assert.match(formProblem(form), /Motor: give its repair time/);
  form.lines = [line({ name: "Motor", mttr: "0" })];
  assert.match(formProblem(form), /more than 0/);
  form.lines = [line({ name: "Motor", mttr: "2", maximum: "2" })];
  assert.match(formProblem(form), /most done by/);
  form.lines = [line({ name: "Motor", mttr: "2", failure_rate: "x" })];
  assert.match(formProblem(form), /failure rate must be a number/);
  form.lines = [line({ name: "Motor", elements: { replace: "2" } }), emptyLine()]; // a trailing blank row is fine
  assert.equal(formProblem(form), null);
  form.percentile = "30";
  assert.match(formProblem(form), /percentile/);
  form.percentile = "95";
  form.mtbf = "0";
  assert.match(formProblem(form), /MTBF/);
});

test("the request carries parsed numbers and leaves blank cells out", () => {
  const form = emptyForm();
  form.unit = "hours";
  form.percentile = "90";
  form.mtbf = "1,000";
  form.product = { id: "p1", name: "Quad" };
  form.lines = [
    line({ ref: "SQ-1", name: "Motor", assembly: "Propulsion", quantity: "4", failure_rate: "180",
           elements: { isolation: "10", replace: "15" }, maximum: "60" }),
    line({ name: "Board", mttr: "30" }),
    emptyLine(),
  ];
  assert.deepEqual(toInputs(form), {
    unit: "hours", failure_rate_unit: "per_million_hours", percentile: 0.9, mtbf: 1000,
    product_id: "p1", product_name: "Quad",
    lines: [
      { name: "Motor", ref: "SQ-1", assembly: "Propulsion", quantity: 4, failure_rate: 180,
        elements: { isolation: 10, replace: 15 }, maximum: 60 },
      { name: "Board", ref: "", assembly: "", quantity: 1, mttr: 30 },
    ],
  });
  assert.ok(isBlank(emptyLine()));
  assert.ok(!isBlank(line({ failure_rate: "1" })));
});

test("a saved prediction's inputs come back as the form, and round-trip", () => {
  const inputs = {
    unit: "minutes", failure_rate_unit: "per_hour", percentile: 0.95, mtbf: 500, product_id: "p1", product_name: "Quad",
    lines: [{ ref: "A-1", name: "A", assembly: "X › Y", quantity: 2, failure_rate: 1e-5,
              elements: { isolation: 5, access: 10, replace: 15, restore: 10, checkout: 5 }, maximum: 90 },
            { name: "B", quantity: 1, mttr: 20, sigma: 0.4 }],
  };
  const form = fromInputs(inputs);
  assert.equal(form.percentile, "95");
  assert.equal(form.lines[0].elements.replace, "15");
  assert.equal(form.lines[1].mttr, "20");
  assert.equal(form.lines[1].sigma, 0.4);
  const back = toInputs(form);
  assert.deepEqual(back.lines[0], inputs.lines[0]);
  assert.deepEqual(back.lines[1], { name: "B", ref: "", assembly: "", quantity: 1, mttr: 20 });
  assert.equal(back.mtbf, 500);
  assert.equal(fromInputs({}).lines.length, 1);
});

test("a pasted parts list: a header row maps the columns", () => {
  const rows = parsePartsList(
    "Part number\tDescription\tQty\tFailure rate\tIsolation\tReplace\n" +
    "SQ-M2210\tBrushless motor\t4\t180\t10\t15\n" +
    "SQ-FC7\tFlight controller\t1\t90\t20\t10\n",
  );
  assert.equal(rows.length, 2);
  assert.equal(rows[0].ref, "SQ-M2210");
  assert.equal(rows[0].name, "Brushless motor");
  assert.equal(rows[0].quantity, "4");
  assert.equal(rows[0].failure_rate, "180");
  assert.deepEqual([rows[0].elements.isolation, rows[0].elements.replace], ["10", "15"]);
  assert.equal(rows[1].name, "Flight controller");
});

test("a pasted parts list without a header: ref, name and quantity are told apart", () => {
  const rows = parsePartsList("SQ-M2210, Brushless motor, 4\nFlight controller, 1\nGPS module\n\nSQ-BP6S;Battery pack;1");
  assert.deepEqual(rows.map((r) => [r.ref, r.name, r.quantity]), [
    ["SQ-M2210", "Brushless motor", "4"],
    ["", "Flight controller", "1"],
    ["", "GPS module", "1"],
    ["SQ-BP6S", "Battery pack", "1"],
  ]);
  assert.deepEqual(parsePartsList(""), []);
  assert.deepEqual(parsePartsList("   \n  "), []);
});

test("rows from a product's parts list keep its refs, quantities and rates", () => {
  const rows = linesFromProduct({ lines: [{ ref: "SQ-1", name: "Motor", assembly: "Arm", quantity: 4, failure_rate: 12 },
                                          { ref: "SQ-2", name: "Board" }] });
  assert.deepEqual([rows[0].ref, rows[0].name, rows[0].assembly, rows[0].quantity, rows[0].failure_rate],
    ["SQ-1", "Motor", "Arm", "4", "12"]);
  assert.equal(rows[1].quantity, "1");
  assert.equal(rows[1].failure_rate, "");
  assert.equal(lineMttr(rows[0]), null);
});

test("the results' element columns are the ones any line uses", () => {
  const cols = usedElements({ lines: [{ elements: { replace: 1 } }, { elements: { isolation: 2, replace: 3 } }] });
  assert.deepEqual(cols.map((c) => c.key), ["isolation", "replace"]);
  assert.equal(usedElements({ lines: [{ elements: {} }] }).length, 0);
  assert.equal(ELEMENTS.length, 5);
});

test("availability keeps its decimals: never rounded up to 100%", () => {
  assert.equal(availabilityText(0.99976), "99.98%");
  assert.equal(availabilityText(0.9997), "99.97%");
  assert.equal(availabilityText(0.999976), "99.998%");
  assert.equal(availabilityText(0.95), "95.00%");
  assert.equal(availabilityText(1), "100.00%");
  assert.equal(availabilityText(null), "—");
});

test("a list row's headline reads in plain words, not symbols", () => {
  assert.equal(plainHeadline("Mct 29.9 minutes · M_max 94.1 minutes · A 99.78%"),
    "Mean repair 29.9 minutes · most done by 94.1 minutes · availability 99.78%");
  assert.equal(plainHeadline("Mct 2.5 hours"), "Mean repair 2.5 hours");
  assert.equal(plainHeadline("Mct 2.5 hours · A 99.9%"), "Mean repair 2.5 hours · availability 99.9%");
  assert.equal(plainHeadline("Maintainability prediction"), "Maintainability prediction");
  assert.equal(plainHeadline(null), "");
});

test("the weights' source in words", () => {
  assert.match(weightsText({ weights: { source: "equal" } }), /counts the same/);
  assert.match(weightsText({ weights: { source: "typed" }, failure_rate_unit: "per_hour" }), /per hour/);
  assert.match(weightsText({ weights: { source: "reliability_prediction", prediction: { name: "Rates" } } }), /“Rates”/);
  assert.equal(weightsText(null), "");
});
