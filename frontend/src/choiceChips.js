// The logic behind ChoiceChips (components/ui/ChoiceChips.jsx), kept apart so
// it's tested without a browser.

// Where an arrow key goes from chip `i` of `n`: the next or previous one,
// round the ends; null for any other key.
export function chipStep(i, key, n) {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[key];
  if (!step || n < 1) return null;
  return (i + step + n) % n;
}

// The value a click on `picked` gives: it, or "" (none) when it's chosen
// already and the chips can be cleared.
export const chipPick = (picked, chosen, clearable) => (clearable && picked === chosen ? "" : picked);

// The chip that takes Tab: the chosen one, else the first.
export const chipTabStop = (options, value) => Math.max(0, options.findIndex((o) => o.value === value));
