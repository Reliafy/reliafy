// A block's replacement rule as typed in "Repairs and replacement" (#367), checked.

const blank = (v) => v === "" || v == null;

// {value, valid, error}: what the block stores, or why it can't.
export function readRule(rule, age, repairs, duration, cost) {
  if (rule === "age") {
    const a = Number(age);
    if (blank(age) || !Number.isFinite(a) || a <= 0) return { valid: false, error: "Enter an age above 0." };
    const out = { rule: "age", age: a };
    if (!blank(duration)) {
      const d = Number(duration);
      if (!Number.isFinite(d) || d < 0) return { valid: false, error: "The replacement time must be 0 or more." };
      out.duration = d;
    }
    if (!blank(cost)) {
      const c = Number(cost);
      if (!Number.isFinite(c) || c < 0) return { valid: false, error: "The replacement cost must be 0 or more." };
      out.cost = c;
    }
    return { valid: true, value: out };
  }
  if (rule === "repairs") {
    const n = Number(repairs);
    if (blank(repairs) || !Number.isInteger(n) || n < 0 || n > 999) {
      return { valid: false, error: "Enter a whole number of repairs, 0 to 999." };
    }
    return { valid: true, value: { rule: "repairs", repairs: n } };
  }
  return { valid: true, value: { rule: "none" } };
}

