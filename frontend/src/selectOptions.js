import { Children, isValidElement } from "react";

// Select's rows from <option> and <optgroup> children, so a form that wrote a
// native <select> keeps its markup: <Select value onChange><option …/></Select>.
// The rows read the way a native list does: every value is a string (an
// <option> with no value takes its text), an <optgroup> is a heading over its
// options, and fragments, arrays and conditionals (false, null) are walked.

// The words of a node: strings and numbers, joined, through any wrapper.
export function textOf(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf(node.props.children);
  return "";
}

export function optionsFromChildren(children) {
  const out = [];
  const walk = (kids, groupDisabled) => {
    Children.forEach(kids, (c) => {
      if (!isValidElement(c)) return;
      if (c.type === "option") {
        const label = textOf(c.props.children).replace(/\s+/g, " ").trim();
        const value = c.props.value != null ? String(c.props.value) : label;
        const row = { value, label };
        if (c.props.disabled || groupDisabled) row.disabled = true;
        out.push(row);
      } else if (c.type === "optgroup") {
        out.push({ heading: c.props.label });
        walk(c.props.children, !!c.props.disabled);
      } else {
        // A fragment (or anything holding options): its children.
        walk(c.props.children, groupDisabled);
      }
    });
  };
  walk(children, false);
  return out;
}

// The row a native list shows for ``value``: the one whose value matches, or
// else its first row that isn't disabled (what a browser shows).
export function nativeSelected(rows, value) {
  const want = value == null ? null : String(value);
  const usable = rows.filter((o) => o.heading == null && !o._header);
  return (want != null && usable.find((o) => o.value === want)) || usable.find((o) => !o.disabled) || null;
}

// About 15 rows and up: the list gets its "Find…" box (the design system).
export const SEARCH_FROM = 15;
export const longList = (rows) => rows.filter((o) => o.heading == null && !o._header).length > SEARCH_FROM;
