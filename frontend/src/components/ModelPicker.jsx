import Select from "./Select.jsx";
import { useEffect, useMemo, useRef, useState } from "react";
import { getDistributions, listModels, getModel, rbdBlockModel, rbdMeanForms } from "../api.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { paramLabel } from "../paramLabels.js";
import { unitInText } from "./unitText.js";
import { formatNumber } from "../format.js";

// The shape or spread a mean leaves open, in the words the Mean entry uses
// (#299): a lognormal "takes mean + spread".
const GIVEN_LABEL = {
  lognormal: { sigma: "Spread σ (log-std)" },
};

// Inline life-model picker: choose a saved (plain-distribution) model or enter
// parameters. Emits the model object (same shape used on RBD nodes) via
// onChange, or null when the selection is incomplete. `rbdBlock` leaves out
// non-parametric (KM/NA) saved models: an RBD block needs a distribution
// (RePyability 0.12 refuses an empirical one).
//
// ``meanEntry`` (the RBD block dialogs, #299) adds "Mean": the model entered
// as its mean — "Mean life (MTBF)" or "Mean repair time (MTTR)", the label
// given — plus the shape or spread it leaves open; the server turns it into
// SurPyval's parameters. ``unit`` (the diagram's) puts the unit on the labels.
export default function ModelPicker({ label, value, onChange, rbdBlock = false, meanEntry = null, unit = "" }) {
  const hasParams = value?.source === "params" && (value.params || []).length > 0;
  const [source, setSource] = useState(
    value?.source === "saved" ? "saved" : hasParams || !meanEntry ? "params" : "mean"
  );
  const [dists, setDists] = useState([]);
  const [saved, setSaved] = useState([]);
  const [forms, setForms] = useState(null); // {distId: {given: [...]}} — which take a mean
  const [distId, setDistId] = useState(
    value?.source === "params" ? value.distribution_id : meanEntry ? "exponential" : "weibull"
  );
  const [pvals, setPvals] = useState(() =>
    Object.fromEntries(
      (value?.source === "params" ? value.params || [] : []).map((p) => [p.name, p.value])
    )
  );
  const [savedId, setSavedId] = useState(
    value?.source === "saved" ? value.modelId : ""
  );
  // Mean entry: the mean, the given shape/spread, the parameters it made
  // (shown under the inputs) and the server's reason when it can't.
  const [meanVal, setMeanVal] = useState("");
  const [given, setGiven] = useState({});
  const [meanOut, setMeanOut] = useState(null); // {params} | {error}
  const reqRef = useRef(0);

  useEffect(() => {
    getDistributions()
      // Manual-parameter entry only makes sense for plain parametric
      // distributions — not "best" (a selector) or non-parametric (no params).
      .then((d) => setDists(d.distributions.filter((x) => !x.covariates && !x.nonparametric && x.id !== "best")))
      .catch(() => {});
    // Include proportional-hazards (regression) models: they can't be entered
    // as plain parameters, but a node can reference a saved one and supply
    // covariate values on the calculator.
    listModels()
      // Fits by failure mode (#177) have no single life distribution to pick.
      .then((d) => setSaved(d.models.filter((m) => m.kind !== "competing_risks"
        && !(rbdBlock && m.kind === "nonparametric"))))
      .catch(() => {});
    if (meanEntry) rbdMeanForms().then(setForms).catch(() => setForms({}));
  }, [rbdBlock, meanEntry]);

  const dist = useMemo(() => dists.find((d) => d.id === distId), [dists, distId]);
  const meanDists = useMemo(() => dists.filter((d) => forms?.[d.id]), [dists, forms]);
  // Mean entry needs a distribution that takes a mean: the exponential (an
  // MTBF on its own) when the one chosen doesn't.
  const meanDistId = forms && !forms[distId] ? "exponential" : distId;

  const modelOf = (id, values) => {
    const d = dists.find((x) => x.id === id);
    return {
      source: "params",
      distribution: d?.name || id,
      distribution_id: id,
      params: values,
    };
  };

  const emitParams = (id, values) => {
    const d = dists.find((x) => x.id === id);
    const names = d?.params || [];
    const ok =
      names.length &&
      names.every(
        (p) => values[p] !== "" && values[p] !== undefined && !Number.isNaN(Number(values[p]))
      );
    onChange(ok ? modelOf(id, names.map((p) => ({ name: p, value: Number(values[p]) }))) : null);
  };

  // A mean (and its shape/spread) to parameters, on the server: SurPyval's
  // own mean, solved for the parameter it leaves free. The latest typing wins.
  const emitMean = (id, mean, givenVals) => {
    const need = forms?.[id]?.given || [];
    const blank = (v) => v === "" || v === undefined || Number.isNaN(Number(v));
    if (blank(mean) || need.some((g) => blank(givenVals[g]))) {
      setMeanOut(null);
      onChange(null);
      return;
    }
    const n = ++reqRef.current;
    onChange(null);
    rbdBlockModel({
      distribution_id: id,
      mean: Number(mean),
      given: Object.fromEntries(need.map((g) => [g, Number(givenVals[g])])),
    })
      .then((out) => {
        if (n !== reqRef.current) return;
        setMeanOut({ params: out.params });
        setPvals(Object.fromEntries(out.params.map((p) => [p.name, p.value])));
        onChange(modelOf(id, out.params));
      })
      .catch((err) => {
        if (n !== reqRef.current) return;
        setMeanOut({ error: err.message });
        onChange(null);
      });
  };

  // Switching to Mean from parameters starts from the model's own mean and
  // shape, so nothing typed is lost.
  const toMean = () => {
    const id = meanDistId;
    const need = forms?.[id]?.given || [];
    const nextGiven = Object.fromEntries(need.map((g) => [g, pvals[g] ?? given[g] ?? ""]));
    setDistId(id);
    setGiven(nextGiven);
    const names = dists.find((x) => x.id === id)?.params || [];
    const complete = id === distId && names.length && names.every((p) => pvals[p] !== "" && pvals[p] != null);
    if (!complete) {
      emitMean(id, meanVal, nextGiven);
      return;
    }
    rbdBlockModel({ distribution_id: id, params: names.map((p) => ({ name: p, value: Number(pvals[p]) })) })
      .then((out) => {
        const m = out.mean != null ? String(Number(out.mean.toPrecision(6))) : "";
        setMeanVal(m);
        emitMean(id, m, nextGiven);
      })
      .catch(() => emitMean(id, meanVal, nextGiven));
  };

  const onPickSaved = async (id) => {
    setSavedId(id);
    if (!id) return onChange(null);
    try {
      const full = await getModel(id);
      const r = full.results || {};
      onChange({
        source: "saved",
        kind: full.kind,
        modelId: id,
        name: full.name,
        distribution: r.distribution,
        distribution_id: r.distribution_id,
        params: r.params || [],
        // Extra fitted quantities (offset/LFP/ZI) so calculators rebuild the
        // model exactly as it was fitted.
        extras: r.extras || null,
        // Covariate field definitions for proportional-hazards models; the RBD
        // calculator prompts for these values.
        covariates: (r.functions && r.functions.covariates) || [],
        unit: r.unit || "",
        // A mixture fit's modes follow this distribution (#318).
        ...(r.distribution_id === "mixture" ? { base_distribution_id: r.base_distribution_id || "weibull" } : {}),
      });
    } catch {
      onChange(null);
    }
  };

  const u = unit ? unitInText(unit) : "";
  const distSelect = (options, valueId, onPick) => (
    <label className="dist-field" style={{ maxWidth: 280 }}>
      <span className="dist-label">Distribution</span>
      <Select
        value={valueId}
        onChange={onPick}
        options={options.map((d) => ({ value: d.id, label: d.name }))}
      />
    </label>
  );

  return (
    <div className="picker">
      {label && <div className="picker-label">{label}</div>}
      <SegmentedControl
        label={label || "Model source"}
        className="picker-seg"
        value={source}
        onChange={(v) => {
          setSource(v);
          if (v === "mean") toMean();
          else if (v === "params") emitParams(distId, pvals);
          else onPickSaved(savedId);
        }}
        options={[
          ...(meanEntry ? [{ value: "mean", label: "Mean" }] : []),
          { value: "params", label: "Parameters" },
          { value: "saved", label: "Saved model" },
        ]}
      />

      {source === "mean" ? (
        <>
          {distSelect(meanDists, meanDistId, (id) => {
            const need = forms?.[id]?.given || [];
            const nextGiven = Object.fromEntries(need.map((g) => [g, given[g] ?? ""]));
            setDistId(id);
            setGiven(nextGiven);
            emitMean(id, meanVal, nextGiven);
          })}
          <div className="param-fields">
            <label className="param-field">
              <span>{meanEntry}{u ? ` (${u})` : ""}</span>
              <input
                type="number"
                step="any"
                min="0"
                value={meanVal}
                onChange={(e) => {
                  setMeanVal(e.target.value);
                  emitMean(meanDistId, e.target.value, given);
                }}
              />
            </label>
            {(forms?.[meanDistId]?.given || []).map((g) => (
              <label className="param-field" key={g}>
                <span>{GIVEN_LABEL[meanDistId]?.[g] || paramLabel(meanDistId, g, unit)}</span>
                <input
                  type="number"
                  step="any"
                  min="0"
                  value={given[g] ?? ""}
                  onChange={(e) => {
                    const next = { ...given, [g]: e.target.value };
                    setGiven(next);
                    emitMean(meanDistId, meanVal, next);
                  }}
                />
              </label>
            ))}
          </div>
          {meanOut?.error && <p className="rbd-dlg-echo is-error" role="alert">{meanOut.error}</p>}
          {meanOut?.params && (
            <p className="rbd-dlg-echo">
              {meanOut.params
                .map((p) => `${paramLabel(meanDistId, p.name, unit)} ${formatNumber(p.value, { sig: 4 })}`)
                .join(" · ")}
            </p>
          )}
        </>
      ) : source === "params" ? (
        <>
          {distSelect(dists, distId, (id) => {
            setDistId(id);
            setPvals({});
            onChange(null);
          })}
          <div className="param-fields">
            {(dist?.params || []).map((p) => (
              <label className="param-field" key={p}>
                <span>{paramLabel(distId, p, unit)}</span>
                <input
                  type="number"
                  step="any"
                  value={pvals[p] ?? ""}
                  onChange={(e) => {
                    const next = { ...pvals, [p]: e.target.value };
                    setPvals(next);
                    emitParams(distId, next);
                  }}
                />
              </label>
            ))}
          </div>
        </>
      ) : saved.length === 0 ? (
        <p className="muted-line">No saved distribution models yet.</p>
      ) : (
        <label className="dist-field" style={{ maxWidth: 320 }}>
          <span className="dist-label">Model</span>
          <Select
            value={savedId}
            onChange={onPickSaved}
            placeholder="— choose —"
            options={[
              { value: "", label: "— choose —" },
              ...saved.map((m) => ({
                value: m.id,
                label: m.name,
                hint: m.distribution + (m.kind === "regression" ? ", covariates" : ""),
              })),
            ]}
          />
        </label>
      )}
    </div>
  );
}
