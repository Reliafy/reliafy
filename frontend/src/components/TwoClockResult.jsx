// A life on two clocks (hours and starts, flight hours and landings...), in the model
// frame's tabs: "Life at a rate" (the answer at a usage rate: the fleet's typical one
// first, any other typed), "Model characteristics" (what one unit of the second clock
// costs, the test that it matters, the life at the fleet's low, typical and high rates,
// the parameters) and Data. Every word uses the model's units. A fresh fit asks its at_rate_path; a saved model its
// /at-rate route.
import { useState } from "react";
import TwoClockLife from "./TwoClockLife.jsx";
import DataTab from "./model/DataTab.jsx";
import { ModelTabs } from "./model/ModelFrame.jsx";
import { ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";
import { fitAtRate, modelAtRate } from "../api.js";
import { modelTabs, resolveTab } from "../modelFrame.js";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import { clockWords, kTestWords, kWords, rateLabel } from "../twoClocks.js";

const pText = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : formatNumber(p, { sig: 2 }));

export default function TwoClockResult({ result, modelId = null, split = null, datasetId = null,
                                         tab: wanted = undefined, onTab = null }) {
  const tabs = modelTabs(result) || [];
  const [own, setOwn] = useState(() => resolveTab(tabs, wanted));
  const tab = resolveTab(tabs, wanted !== undefined && onTab ? wanted : own);
  const setTab = (id) => { setOwn(id); onTab?.(id); };
  const [atRate, setAtRate] = useState(result.at_rate || null);
  const [busy, setBusy] = useState(false);
  const unit = result.unit || "Hours";
  const u = unitInText(unit) || "hours";
  const words = clockWords(result.clocks, u, result.second_unit);

  const ask = async (rate) => {
    setBusy(true);
    try {
      const path = result.functions?.at_rate_path;
      const out = modelId ? await modelAtRate(modelId, { rate }) : path ? await fitAtRate(path, { rate }) : null;
      if (out) setAtRate(out);
    } finally { setBusy(false); }
  };

  let body = null;
  if (tab === "rate") {
    body = (
      <div className="detail-panel tc-panel">
        <p className="tc-headline">{kWords(result)}</p>
        <TwoClockLife atRate={atRate} unit={unit} onRate={ask} busy={busy} clocks={words} />
      </div>
    );
  } else if (tab === "chars") {
    body = (
      <TablePanel main={<>
        <ScrollCard title={`What a ${words.second_one} costs`}>
          <p>{kWords(result)}</p>
          <p className="muted-line">{kTestWords(result, pText)}</p>
        </ScrollCard>
        <ScrollCard title="Life by duty" sub={`The fleet's own low, typical and high ${words.rate_unit}; B10 with its 90% lower bound.`}>
          <div className="maint-scroll">
            <table className="mini-table">
              <thead><tr><th></th><th>{rateLabel(words)}</th><th>B10 life ({u})</th><th>At least (90%)</th><th>Mean life ({u})</th></tr></thead>
              <tbody>
                {(result.rate_table || []).map((r) => (
                  <tr key={r.label}>
                    <td>{r.label}</td><td>{r.rate_words}</td><td>{formatNumber(r.b10)}</td>
                    <td>{formatNumber(r.b10_lower)}</td><td>{formatNumber(r.mean)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ScrollCard>
        <ScrollCard title="Parameters" sub={`${result.distribution}; 90% two-sided intervals.`}>
          <div className="maint-scroll">
            <table className="mini-table">
              <thead><tr><th>Parameter</th><th>Value</th><th>90% range</th></tr></thead>
              <tbody>
                {(result.params || []).map((p) => (
                  <tr key={p.name}>
                    <td><code>{p.name}</code> {p.words}</td><td>{formatNumber(p.value, { sig: 4 })}</td>
                    <td>{p.ci?.[0] != null ? `${formatNumber(p.ci[0])}–${formatNumber(p.ci[1])}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted-line">
            alpha is in combined {u} ({u} plus k × {words.second_word}); k is in {u} per {words.second_one}.
          </p>
        </ScrollCard>
      </>} />
    );
  } else if (tab === "data") {
    body = <DataTab result={result} split={split || result.split} datasetId={datasetId} />;
  }
  return <ModelTabs tabs={tabs} value={tab} onChange={setTab}>{body}</ModelTabs>;
}
