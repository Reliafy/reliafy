import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TablePane from "./TablePane.jsx";
import Tabs from "./ui/Tabs.jsx";
import OptimalReplacement from "./OptimalReplacement.jsx";
import CalendarReplacement from "./CalendarReplacement.jsx";
import FailureFinding from "./FailureFinding.jsx";
import OverhaulReplace from "./OverhaulReplace.jsx";
import RecurrentOverhaul from "./RecurrentOverhaul.jsx";
import { getPositionClass } from "../api.js";
import { explorerPath } from "../assetTree.js";
import { classPresets, rowInputs, strategiesFor } from "../positionStrategy.js";
import "./StrategyPane.css";
import { classKey } from "../positionClass.js";

// A model's Strategy on a position, in the Explorer's table area beside the tree (the Modelling
// tab): the strategies saved for it there, then the strategy tools that fit the model's type as
// tabs, each the very same component as its Strategy page (one per job), opened on the model and
// the position's class costs where known. A Save keeps the model's row with the analysis, so the
// row shows its Strategy item (Strategy is optional: Derryn, 16 Nov 2026).
//
//   link      the model's row on the position (GET /api/maintenance/position-models)
//   saved     the strategies saved for it (positionStrategy.strategiesByLink)
//   how       the tool open (?how=), or none: the first; onHow(id) changes it (the address)
export default function StrategyPane({ link, position, saved = [], how = null, onHow, phone = false, headingRef = null, onClose }) {
  const { choices, none } = strategiesFor(link);
  const tool = choices.find((c) => c.id === how) || choices[0] || null;
  const [cls, setCls] = useState(null);
  useEffect(() => {
    let live = true;
    const name = classKey(position);
    if (!name) { setCls(null); return undefined; }
    getPositionClass(name).then((c) => live && setCls(c)).catch(() => live && setCls(null));
    return () => { live = false; };
  }, [position.position_class, position.class_key]);
  const pre = classPresets(cls);
  const extra = rowInputs(link);
  const modelName = link.model?.name || link.name || "the model";
  const from = [pre.planned != null || pre.unplanned != null || pre.target != null || pre.replace != null]
    .some(Boolean) && cls ? `Costs start from its class, ${cls.position_class}.` : null;

  let body = null;
  if (tool) {
    const key = `${tool.id}:${link.id}:${cls ? "c" : "-"}`;
    switch (tool.id) {
      case "replacement":
        body = <OptimalReplacement key={key} modelId={link.model_id} planned={pre.planned} unplanned={pre.unplanned} extraInputs={extra} />;
        break;
      case "calendar":
        body = <CalendarReplacement key={key} modelId={link.model_id} failure={pre.unplanned} extraInputs={extra} />;
        break;
      case "failureFinding":
        body = <FailureFinding key={key} modelId={link.model_id} target={pre.target} extraInputs={extra} />;
        break;
      case "overhaulReplace":
        body = <OverhaulReplace key={key} modelId={link.model_id} lockModel compact extraInputs={extra}
                                presets={{ cost_replace: pre.replace }} defaultName={`Overhaul and replace · ${position.name}`} />;
        break;
      case "overhaul":
        body = <RecurrentOverhaul key={key} modelId={link.model_id} unit={link.model?.unit} name={modelName} />;
        break;
      case "conditionRisk":
        body = (
          <p className="sp-link">
            {tool.words} <Link to={`${link.model?.path || `/models/joint/${link.model_id}`}?tab=risk`}>Open {modelName} at Risk now →</Link>
          </p>
        );
        break;
      case "conditionMonitoring":
        body = (
          <p className="sp-link">
            {tool.words} <Link to={explorerPath("positions", { root: position.root || null, sel: position.id, tab: "condition" })}>Open its Condition monitoring →</Link>
          </p>
        );
        break;
      default:
    }
  }

  return (
    <TablePane title="Strategy" subject={`${modelName} · ${position.name}`} phone={phone} headingRef={headingRef}
               onClose={onClose} className="strategy-pane">
      <div className="sp-body">
        {saved.length > 0 && (
          <section className="sp-saved" aria-labelledby="sp-saved-h">
            <h3 id="sp-saved-h" className="sp-h">Saved for this model here</h3>
            <ul className="strategy-saved-list">
              {saved.map((a) => (
                <li key={a.id}>
                  <Link to={`/strategy/analyses/${encodeURIComponent(a.id)}`}>{a.name}</Link>
                  {a.headline && <span className="strategy-saved-result">{a.headline}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}
        {!choices.length ? <p className="hint">{none}</p> : (
          <>
            {choices.length > 1 && (
              <Tabs label="Strategies for this model" idPrefix="sp" value={tool.id} onChange={(id) => onHow?.(id)}
                    tabs={choices.map((c) => ({ id: c.id, label: c.label, title: c.words }))} />
            )}
            <div id="sp-panel" role={choices.length > 1 ? "tabpanel" : undefined} className="sp-tool">
              <p className="sp-what">{tool.words}{from ? ` ${from}` : ""}</p>
              {body}
            </div>
          </>
        )}
      </div>
    </TablePane>
  );
}
