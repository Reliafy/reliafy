import { useCallback, useEffect, useRef, useState } from "react";
import { getTaskTable } from "../api.js";
import Chip from "./ui/Chip.jsx";
import TablePane from "./TablePane.jsx";
import PositionForecast from "./PositionForecast.jsx";
import MaintenanceTask, { TradeRates } from "./MaintenanceTask.jsx";
import RbdTaskUses from "./RbdTaskUses.jsx";
import { CloseIcon, ExpandIcon, ShrinkIcon } from "./icons.jsx";
import { fmtDate } from "./MaintenanceParts.jsx";
import { latestOnly } from "../explorerMissions.js";
import { taskCell } from "../explorerTasks.js";
import "./LsaPanel.css";

// The Explorer's Maintenance tab is the tree with each position's tasks in it (explorerTasks.js),
// like the Modelling and Missions tabs: the read of every task in the asset opened, each task
// row's cells and its phone line, a task's details beside the table, and a level's forecast in the
// table area.

export { TASK_COLUMNS, TASK_TREE_HEAD } from "../explorerTasks.js";

// Every task in the asset opened (`within`: its top row's id), read when the tab is on (and again
// on `load`): one read, the server's roll-up. The last read asked for is the one shown.
// `kind`: the top row's type ("pos" or "loc"), so the read names it as a position or a place too.
export function useTreeTasks({ on, within = null, kind = "pos" }) {
  const [state, setState] = useState({ tasks: null, truncated: false, total: 0, error: null });
  const asked = useRef(null);
  if (!asked.current) asked.current = latestOnly();
  const load = useCallback(() => {
    if (!within) {
      setState({ tasks: [], truncated: false, total: 0, error: "Open one asset to see its tasks." });
      return Promise.resolve();
    }
    const latest = asked.current();
    return getTaskTable({ [kind === "loc" ? "location_id" : "position_id"]: within, within })
      .then((d) => latest() && setState({ tasks: d.tasks || [], truncated: !!d.truncated, total: d.total || 0, error: null }))
      .catch((e) => latest() && setState((s) => ({ ...s, error: e.message })));
  }, [within, kind]);
  useEffect(() => { if (on) load(); }, [on, load]);
  return { ...state, load };
}

// One cell of a task row (r.ref.task: a task-table row).
export function TaskCell({ r, col }) {
  const t = r.ref.task;
  const c = taskCell(t, col.id);
  if (col.id === "due") {
    if (!c.text) return <span className="rw-blank">—</span>;
    return <span className={"ml-num" + (c.overdue ? " pk-overdue" : "")} title={c.title || undefined}>{fmtDate(c.text)}{c.overdue ? " · overdue" : ""}</span>;
  }
  if (col.id === "kind") {
    return c.text ? <Chip tone={t.on_event ? "neutral" : "accent"} className="pk-kind" title={c.text}>{c.text}</Chip> : null;
  }
  if (!c.text) return c.blank ? <span className="rw-blank" title={c.title || undefined}>{c.blank}</span> : null;
  return <span className={col.num ? "ml-num" : "ml-src"} title={c.title || c.text}>{c.text}</span>;
}

// A row's second line on a phone: a task's interval, next due and cost; a level's roll-up.
export function taskPhoneRow(r, rollup) {
  if (r.type !== "mtask") return { line: rollup || "", status: null };
  const t = r.ref.task;
  const due = taskCell(t, "due");
  const cost = taskCell(t, "cost");
  return {
    line: [taskCell(t, "interval").text, cost.text ? `${cost.text} each time` : null, t.package?.name].filter(Boolean).join(" · "),
    status: due.text ? <Chip tone={due.overdue ? "danger" : "neutral"} title={due.title || undefined}>{due.overdue ? "Overdue " : "Due "}{fmtDate(due.text)}</Chip> : null,
  };
}

// Beside the table: a task opened (its form, MaintenanceTask.jsx), a new task on a level, or the
// trade rates. `holder`: the position or place row the task is on (or is being added to);
// `taskName`: the opened task's name from its row, the panel's title until the task has loaded.
// The head (where it is, Expand or Back to table, Close) is the same as the Models and RCM panels';
// the task's form draws its own title, body and footer under it, so its Save sits in the footer.
export function TaskSide({ holder, taskId = null, taskName = "", rates = false, phone, expanded = false, onExpand, onCollapse, headingRef, onClose, onDone, onChanged, onOptimise = null }) {
  const title = rates ? "Trade rates" : taskId ? (taskName || "Maintenance task") : "Add a task";
  const head = (
    <div className="rw-panel-head">
      <div className="rw-panel-kind">{rates || taskId ? (holder?.ref?.name || "Maintenance task") : "New maintenance task"}</div>
      <div className="rw-panel-btns">
        {!phone && taskId && onExpand && (expanded ? (
          <button type="button" className="ghost sm rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)" aria-label="Back to table"><ShrinkIcon /></button>
        ) : (
          <button type="button" className="ghost sm rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them" aria-label="Expand the details"><ExpandIcon /></button>
        ))}
        <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label={`Close ${rates ? "trade rates" : taskId ? "the task" : "add a task"}`} title="Close (Esc)"><CloseIcon /></button>
      </div>
    </div>
  );
  return (
    <aside className={"rw-panel mt-panel mt-task-panel" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label={title}
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented || e.target.closest("input, textarea, select")) return;
             e.stopPropagation();
             if (expanded && onCollapse) onCollapse(); else onClose();
           }}>
      {rates ? (
        <>
          <div className="rw-panel-top">
            {head}
            <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{title}</h2>
          </div>
          <div className="rw-pbody pk-panel">
            <TradeRates onChanged={onChanged} />
          </div>
        </>
      ) : holder && (
        <MaintenanceTask key={`${holder.key}:${taskId || "new"}`} row={holder} taskId={taskId} taskName={taskName}
                         head={head} headingRef={headingRef} onBack={onClose} onDone={onDone} onOptimise={taskId ? onOptimise : null}
                         uses={taskId ? <RbdTaskUses taskIds={[taskId]} /> : null} />
      )}
    </aside>
  );
}

// A level's forecast in the table area (Forecast… on a position on this tab): the same forecast as
// Maintenance › Forecast, for that position and everything inside it, inside the asset opened.
export function ForecastPane({ position, root, phone, headingRef, onClose }) {
  return (
    <TablePane title="Forecast" subject={position.name} phone={phone} headingRef={headingRef} onClose={onClose}
               closeLabel="Close the forecast">
      <div className="td-tab-page pk-panel rw mt-forecast-pane">
        <PositionForecast positionId={position.id} name={position.name} root={root || null} />
      </div>
    </TablePane>
  );
}
