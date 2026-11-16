// A life on hours and starts at one usage rate: the one shared view of it (the
// model page's "Life at a rate" tab, the Explorer's panel). The answer first
// (ResultSummary), the rate it is for (typed, or where it came from, with a way
// back), then the reliability over hours with its 90% band.
//
//   atRate    the server's answer at a rate (two_clocks.at_rate): life, curves, sentence
//   unit      the first clock's unit ("Hours")
//   onRate    (rate) => Promise: ask for another rate (the parent fetches and passes atRate back)
//   source    optional: { text, kind } where the rate came from (an operating plan, set by hand)
//   onReset   optional: () => Promise — go back to the rate from the source (the plan's)
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
import { bLife, parseRate, rateText } from "../twoClocks.js";

export default function TwoClockLife({ atRate, unit, onRate, source = null, onReset = null, busy = false, compact = false }) {
  const [text, setText] = useState(rateText(atRate?.rate));
  const [error, setError] = useState(null);
  useEffect(() => { setText(rateText(atRate?.rate)); }, [atRate?.rate]);
  const u = unitInText(unit || atRate?.unit || "") || "hours";

  const apply = async (e) => {
    e?.preventDefault();
    const parsed = parseRate(text);
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
            { label: "Combined hours per hour", value: formatNumber(atRate.acceleration),
              hint: "Each hour of running ages it this much, starts included" },
          ]}
        />
      )}
      <form className="tc-rate" onSubmit={apply}>
        <Field label="Starts per hour" error={error}
               help={source?.text || "0.125 is 1 start every 8 hours; 1/8 works too."}>
          <TextInput value={text} inputMode="decimal" onChange={(e) => setText(e.target.value)}
                     aria-label="Starts per hour" />
        </Field>
        <div className="tc-rate-actions">
          <Button variant="secondary" type="submit" disabled={busy}>{busy ? "Working…" : "Use this rate"}</Button>
          {onReset && source?.kind === "set" && (
            <Button variant="ghost" onClick={onReset} disabled={busy}>Use the operating plan's rate</Button>
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
