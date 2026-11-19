// A life on two clocks at one usage rate: the one shared view of it (the model
// page's "Life at a rate" tab, the Explorer's panel). The answer first
// (ResultSummary), the rate it is for (typed, or where it came from, with a way
// back), then the reliability over the first clock with its 90% band. Every
// word uses the model's units ("landings per hour").
//
//   atRate    the server's answer at a rate (two_clocks.at_rate): life, curves, sentence, clocks
//   unit      the first clock's unit ("Hours")
//   clocks    optional: the clocks' words when there's no atRate yet (the result's, the Explorer's)
//   onRate    (rate) => Promise: ask for another rate (the parent fetches and passes atRate back)
//   source    optional: { text, kind } where the rate came from (an operating plan, set by hand)
//   onReset   optional: () => Promise — go back to the rate from the source (the plan's, or the fleet's)
//   resetLabel  optional: the reset button's words ("Use the operating plan's rate")
//   busy      a request is in flight
import { useEffect, useState } from "react";
import Plot from "./Plot.jsx";
import ResultSummary from "./ui/ResultSummary.jsx";
import Field from "./ui/Field.jsx";
import { TextInput } from "./ui/Controls.jsx";
import Button from "./ui/Button.jsx";
import { bandPair, fitLine } from "../plotTheme.js";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import { bLife, clockWords, parseRate, rateHint, rateLabel, rateText } from "../twoClocks.js";

export default function TwoClockLife({ atRate, unit, onRate, source = null, onReset = null, busy = false, compact = false,
                                       clocks = null, resetLabel = "Use the operating plan's rate" }) {
  const [text, setText] = useState(rateText(atRate?.rate));
  const [error, setError] = useState(null);
  useEffect(() => { setText(rateText(atRate?.rate)); }, [atRate?.rate]);
  const u = unitInText(unit || atRate?.unit || "") || "hours";
  const words = clockWords(atRate?.clocks || clocks, u);
  const label = rateLabel(words);

  const apply = async (e) => {
    e?.preventDefault();
    const parsed = parseRate(text, words);
    if (parsed.error) { setError(parsed.error); return; }
    setError(null);
    try { await onRate(parsed.rate); } catch (err) { setError(err.message || "That rate couldn't be used."); }
  };

  const b10 = bLife(atRate, "B10");
  const b1 = bLife(atRate, "B1");
  const mean = atRate?.life?.mttf?.value;
  const c = atRate?.curves || {};
  const traces = c.x ? [
    ...(c.sf_lower && c.sf_upper ? bandPair(c.x, c.sf_lower, c.sf_upper, { name: "90% band" }) : []),
    fitLine({ x: c.x, y: c.sf, name: `Reliability at ${atRate.rate_words}` }),
  ] : [];

  return (
    <div className={"tc-life" + (compact ? " tc-compact" : "")}>
      <div className="tc-left">
      {atRate && (
        <ResultSummary
          sentence={<>At <b>{atRate.rate_words}</b>, its B10 life is <b>{formatNumber(b10?.value)} {u}</b>
            {b10?.lower != null && <> (at least <b>{formatNumber(b10.lower)} {u}</b>, 90% one-sided)</>}.</>}
          stats={[
            { label: "B10 life", value: `${formatNumber(b10?.value)} ${u}`,
              hint: b10?.lower != null ? `at least ${formatNumber(b10.lower)} ${u} (90%)` : undefined },
            { label: "B1 life", value: `${formatNumber(b1?.value)} ${u}`,
              hint: b1?.lower != null ? `at least ${formatNumber(b1.lower)} ${u} (90%)` : undefined },
            mean != null && { label: "Mean life", value: `${formatNumber(mean)} ${u}` },
            { label: `Combined ${words.first_word} per ${words.first_one}`, value: formatNumber(atRate.acceleration),
              hint: `Each ${words.first_one} ages it this much, ${words.second_word} included` },
          ]}
        />
      )}
      <form className="tc-rate" onSubmit={apply}>
        <Field label={label} error={error} help={source?.text || rateHint(words)}>
          <TextInput value={text} inputMode="decimal" onChange={(e) => setText(e.target.value)}
                     aria-label={label} />
        </Field>
        <div className="tc-rate-actions">
          <Button variant="secondary" type="submit" disabled={busy}>{busy ? "Working…" : "Use this rate"}</Button>
          {onReset && source?.kind === "set" && (
            <Button variant="ghost" onClick={onReset} disabled={busy}>{resetLabel}</Button>
          )}
        </div>
      </form>
      </div>
      {traces.length > 0 && (
        <div className="tc-plot">
          <Plot data={traces} useResizeHandler style={{ width: "100%", height: compact ? 220 : 280 }}
                layout={{ xaxis: { title: { text: unit || "Hours" }, rangemode: "tozero" },
                          yaxis: { title: { text: "Reliability" }, range: [0, 1.02] },
                          margin: { t: 16, r: 8 }, legend: { orientation: "h", y: 1.12 } }}
                download="Life at a usage rate" />
        </div>
      )}
    </div>
  );
}
