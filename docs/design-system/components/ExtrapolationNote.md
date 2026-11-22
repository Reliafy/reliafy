# ExtrapolationNote

The one warning that an answer lies outside the data behind it. Use it wherever a number is read off a fitted curve beyond what was observed, so the warning looks and reads the same everywhere.

- **A life model's Calculator:** a time typed or found before the first failure in the data, or past the oldest age seen (the fit's `data_range`).
- **An accelerated life model:** a use stress outside the tested stresses, on Life-stress and the Calculator.

## Look

A caveat box: `warning-bg` with a `warning-border` edge and `warning-text` (the `.calc-warn` style), `radius-md`, 13/20 text. It starts with "!" so the tone isn't colour alone, and screen readers hear "Extrapolation:" first.

## Props

- `words`: the sentence, from `extrapolation.js` (`timeExtrapolation`, `stressExtrapolation`). Renders nothing when empty.
- `className`: optional extra class.

## Words

Say where the answer is against the data, in the data's units, then what the answer rests on: "833 hours is before the first failure in the data (1,500 hours). The answer comes from the fitted curve's shape alone…". Never a verdict. Show the answer anyway; the analyst decides.
