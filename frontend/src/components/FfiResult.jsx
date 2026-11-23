import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatPercent, formatPlain, formatTarget, formatWithUnit as fmtUnit } from "../format.js";
import { unitInText } from "./unitText.js";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { formatCost } from "../money.js";

// Presentational renderer for a failure-finding-interval result — used by the
// live tool, saved analyses and the public link. Answer first (#311): the
// test interval in one sentence with its cautious (90% one-sided) end, the
// MTTF behind it, then how it was worked out under Details (#313).
// ``actions`` (the live tool's Save) sits with the answer. Analyses saved
// before the interval came from the model's curve keep their old reading.
// Plain figures at any size: "2.01e-7 hours" hid an MTBF typed as a rate.
const formatWithUnit = (v, unit, opts) => fmtUnit(v, unit, { ...opts, plain: true });

export default function FfiResult({ result, actions = null, stale = false }) {
  const currency = useCurrency();
  const unit = result?.unit ? unitInText(result.unit) : "";
  const every = formatWithUnit(result.interval, unit);
  // The target as typed: 99.5% never reads as 100%.
  const target = formatTarget(result.target_availability);
  const legacy = result.method !== "mean_unavailability";
  const bound = result.interval_bound;
  const cautious = bound ? formatWithUnit(bound.interval, unit) : null;
  const rough = legacy && result.target_availability < 0.9;
  // The other answer to "does a test renew the device?", side by side with this one.
  const other = !legacy && result.other_interval != null ? formatWithUnit(result.other_interval, unit) : null;
  const otherDiffers = other && Math.abs(result.other_interval - result.interval) > 0.05 * result.interval;

  return (
    <>
      <ResultSummary
        tone={stale ? "neutral" : rough || (result.warnings || []).length ? "caveat" : "neutral"}
        sentence={
          <>
            Test every <b>≈ {every}</b> to keep average availability at <b>{target}</b>.
            {cautious && <> On the cautious 90% bound of the fit, every <b>{cautious}</b>.</>}
            {otherDiffers && (result.renewed_at_test
              ? <> That assumes each test renews the device; if a test leaves it as it was, every <b>{other}</b>.</>
              : <> That assumes a test leaves a working device as it was; if each test renews it, every <b>{other}</b>.</>)}
          </>
        }
        stats={[
          { label: "Test every", value: `≈ ${every}` },
          cautious && { label: "Cautious end", value: cautious, hint: "90% one-sided" },
          otherDiffers ? {
            label: result.renewed_at_test ? "If a test doesn't renew it" : "If each test renews it",
            value: `≈ ${other}`, hint: "the other answer",
          } : { label: "MTTF", value: formatWithUnit(result.mttf, unit) },
          result.tests_cost_per_year != null && {
            label: "Tests a year", value: formatCost(result.tests_cost_per_year, currency, { sig: 3 }),
            hint: `${formatPlain(result.tests_per_year, { sig: 3 })} tests`,
          },
        ]}
      >
        {stale && "The inputs changed: Compute to update."}
        {!stale && rough && "Below about 90% the approximation is conservative: the true interval can be longer."}
      </ResultSummary>
      {actions && <div className="rs-actions">{actions}</div>}
      {!stale && (result.warnings || []).filter((w) => !(otherDiffers && w.startsWith("If ")))
        .map((w) => <p key={w} className="calc-warn">{w}</p>)}

      <ResultDetails
        rows={legacy ? [] : [
          { label: "Each test", value: result.renewed_at_test ? "renews the device" : "leaves a working device as it was" },
          otherDiffers && { label: "MTTF", value: formatWithUnit(result.mttf, unit) },
          result.test_duration > 0 && { label: "Off-line per test", value: formatWithUnit(result.test_duration, unit) },
          { label: "Constant-rate shortcut, 2 × (1 − A) × MTTF", value: formatWithUnit(result.shortcut_interval, unit) },
        ]}
      >
        {legacy ? (
          <p className="rs-note">
            A hidden failure (a protective device) stays undetected until the function is demanded or
            checked. Testing every {every} keeps its average unavailability near{" "}
            {formatPercent(1 - result.target_availability)}. Interval = 2 × (1 − availability) × MTTF ={" "}
            2 × {formatNumber(1 - result.target_availability)} × {formatNumber(result.mttf, { sig: 4 })}, the
            standard first-order approximation (saved before the interval came from the model's curve).
          </p>
        ) : (
          <>
            <p className="rs-note">
              A hidden failure stays undetected until the device is demanded or tested. The interval is the longest
              that keeps the share of time the device sits failed and unnoticed at{" "}
              {formatTarget(1 - result.target_availability)}, worked out from the model's own curve:{" "}
              {result.renewed_at_test
                ? "with each test renewing the device, that share is 1 − (1/T) ∫ R(t) dt over the interval T."
                : "with a working device left as it was, it builds up until a test finds the failure."}
              {result.test_duration > 0 && " Time off-line for the test counts as unavailable."}
            </p>
            {bound && <p className="rs-note">{result.bound_note}</p>}
            {!bound && result.bound_note && <p className="rs-note">{result.bound_note}</p>}
          </>
        )}
      </ResultDetails>
    </>
  );
}
