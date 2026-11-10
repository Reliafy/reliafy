// Two charts that share a box, each kept wide enough to read (chartPair.js
// has the rule). Side by side where each gets about 480 px; where they
// don't, charts read ``together`` go one under the other, and alternatives
// show one at a time at full width with a switch above naming each. On a
// phone both stack. With one item it is just that item.
//
//   items     [{ id, label, node }] (label: the switch's words; a verdict
//             chip can go in it, so a check's result shows without a click)
//   together  the two are read together: never behind a switch
//   label     accessible name of the switch
import { useLayoutEffect, useRef, useState } from "react";
import SegmentedControl from "../ui/SegmentedControl.jsx";
import usePhone from "../../usePhone.js";
import { pairLayout, shownItem } from "../../chartPair.js";
import "./ChartPair.css";

export default function ChartPair({ items, together = false, label = "Chart", className }) {
  const list = (items || []).filter(Boolean);
  const box = useRef(null);
  const phone = usePhone();
  const [width, setWidth] = useState(null);
  const [chosen, setChosen] = useState(null);
  const pair = list.length > 1;
  // Measured before the first paint, so no chart is drawn at a size it won't keep.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const measure = () => setWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [pair]);
  if (!pair) return list[0]?.node ?? null;
  const layout = pairLayout({ width, phone, together });
  const shown = layout === "switch" ? [shownItem(list, chosen)] : layout ? list : [];
  return (
    <div ref={box} className={"chart-pair" + (layout ? ` chart-pair-${layout}` : "") + (className ? ` ${className}` : "")}>
      {layout === "switch" && (
        <SegmentedControl
          size="sm"
          label={label}
          className="chart-pair-pick"
          value={shown[0].id}
          onChange={setChosen}
          options={list.map((it) => ({ value: it.id, label: it.label }))}
        />
      )}
      <div className="chart-pair-cells">
        {shown.map((it) => <div className="chart-pair-cell" key={it.id}>{it.node}</div>)}
      </div>
    </div>
  );
}
