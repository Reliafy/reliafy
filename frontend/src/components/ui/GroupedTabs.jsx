// A short row of tabs where the grouped ones are drop-downs (the Explorer's panel:
// Summary | Analysis ▾ | Operation ▾ | History ▾). A plain group (one entry named as the group) is
// an ordinary tab; the others open a menu of their entries (the app's row menu, RowMenu: ↑ ↓,
// Enter, Esc), the entry shown ticked. The group the panel is in is the active tab and names the
// entry shown ("Operation: Maintenance ▾"; on a narrow screen the entry alone), so it's always
// clear where you are. When the entry shown has inner views (Maintenance: Tasks · What it needs …)
// they follow as a segmented control, wrapping onto a second line when the row is narrow (never a
// sideways scroll).
//
// Keyboard: the row is one stop in the Tab order (a roving tabindex on the active tab); ← → Home
// End move along it; ↓, Enter or Space opens a group's menu; Esc closes it, the focus back on its
// tab.
//
//   groups    [{id, label, title?, entries: [{id, label, title?, views: [{id, label, title?}]}]}]
//   at        {group, entry, view}: where the panel is
//   onChoose  (entryId, viewId|null) => void
//   label     the row's accessible name
//   idPrefix  ids for the tabs (`${idPrefix}-tab-${group}`) and the panel they control
//   labelOf   (group, at, {short}) => the words on a group's tab
//   isPlain   (group) => is it a plain tab (no menu)
import { useRef, useState } from "react";
import RowMenu from "../RowMenu.jsx";
import SegmentedControl from "./SegmentedControl.jsx";
import { panelId, tabId } from "./Tabs.jsx";
import "./GroupedTabs.css";

const ROW_KEYS = { ArrowRight: 1, ArrowLeft: -1 };

export default function GroupedTabs({ groups, at, onChoose, label, idPrefix = "gt", labelOf, isPlain, className = "" }) {
  const refs = useRef({});
  const [open, setOpen] = useState(null); // {id, at: {x, y}}
  const active = groups.some((g) => g.id === at?.group) ? at.group : groups[0]?.id;
  const [focusId, setFocusId] = useState(null);
  const tabStop = groups.some((g) => g.id === focusId) ? focusId : active;
  const openMenu = (g) => {
    const r = refs.current[g.id].getBoundingClientRect();
    setOpen({ id: g.id, at: { x: r.left, y: r.bottom + 2 } });
  };
  const activate = (g) => {
    if (isPlain(g)) onChoose(g.entries[0].id, null);
    else if (open?.id === g.id) setOpen(null);
    else openMenu(g);
  };
  const onKeyDown = (e, i) => {
    const g = groups[i];
    let next = null;
    if (ROW_KEYS[e.key]) next = (i + ROW_KEYS[e.key] + groups.length) % groups.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = groups.length - 1;
    else if (e.key === "ArrowDown" && !isPlain(g)) { e.preventDefault(); openMenu(g); return; }
    if (next == null) return;
    e.preventDefault();
    setFocusId(groups[next].id);
    refs.current[groups[next].id]?.focus();
  };
  const group = groups.find((g) => g.id === at?.group);
  const entry = group?.entries.find((x) => x.id === at.entry);
  const views = entry && entry.views.length > 1 ? entry.views : null;
  const menuGroup = open && groups.find((g) => g.id === open.id);
  return (
    <div className={"gtabs" + (className ? " " + className : "")}>
      <div className="gtabs-row" role="tablist" aria-label={label}>
        {groups.map((g, i) => {
          const plain = isPlain(g);
          const on = g.id === active;
          const full = labelOf(g, at);
          const short = labelOf(g, at, { short: true });
          return (
            <button
              key={g.id}
              ref={(el) => { refs.current[g.id] = el; }}
              type="button"
              role="tab"
              id={tabId(idPrefix, g.id)}
              aria-controls={panelId(idPrefix)}
              aria-selected={on}
              aria-haspopup={plain ? undefined : "menu"}
              aria-expanded={plain ? undefined : open?.id === g.id}
              aria-label={plain ? undefined : full}
              tabIndex={tabStop === g.id ? 0 : -1}
              className={"tab gtab" + (on ? " active" : "") + (plain ? "" : " gtab-menu") + (open?.id === g.id ? " open" : "")}
              title={g.title}
              onFocus={() => setFocusId(g.id)}
              onClick={() => activate(g)}
              onKeyDown={(e) => onKeyDown(e, i)}
            >
              {full === short ? full : (
                <>
                  <span className="gtab-full">{full}</span>
                  <span className="gtab-short" aria-hidden="true">{short}</span>
                </>
              )}
              {!plain && <span className="gtab-caret" aria-hidden="true">▾</span>}
            </button>
          );
        })}
      </div>
      {views && (
        <SegmentedControl size="sm" className="gtabs-views" label={`${entry.label}: what to show`} value={at.view}
                          onChange={(v) => onChoose(entry.id, v)}
                          options={views.map((v) => ({ value: v.id, label: v.label, title: v.title }))} />
      )}
      {menuGroup && (
        <RowMenu
          items={menuGroup.entries.map((x) => ({ id: x.id, label: x.label, checked: at?.group === menuGroup.id && at.entry === x.id }))}
          at={open.at}
          label={menuGroup.label}
          anchorId={tabId(idPrefix, menuGroup.id)}
          onClose={() => { const id = open.id; setOpen(null); refs.current[id]?.focus({ preventScroll: true }); }}
          onChoose={(id) => onChoose(id, null)}
        />
      )}
    </div>
  );
}
