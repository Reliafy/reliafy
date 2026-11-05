import { useId, useRef, useState } from "react";
import RowMenu from "../RowMenu.jsx";
import { MoreIcon } from "../icons.jsx";

// A ⋯ button that opens a small menu (#UI) of an item's actions: Edit, Move
// up, Move down, Remove. The app's row menu (RowMenu: arrows, Enter, Esc),
// opened under the button; the focus goes back to the button after.
//
//   label   what it's for: "Actions for pH 7.4–7.6" (the button's name)
//   items   [{id, label, danger?, disabled?, reason?, onSelect}]
export default function MoreMenu({ label, items, className = "", disabled = false }) {
  const btn = useRef(null);
  // The menu closes when a scroll moves its button (not on any scroll nearby).
  const id = `more-${useId()}`;
  const [at, setAt] = useState(null);
  const open = () => {
    const r = btn.current.getBoundingClientRect();
    setAt({ x: r.right, y: r.bottom + 4 });
  };
  return (
    <>
      <button ref={btn} id={id} type="button" className={"ghost sm more-btn" + (className ? ` ${className}` : "")} aria-label={label} title={label}
              aria-haspopup="menu" aria-expanded={!!at} disabled={disabled} onClick={() => (at ? setAt(null) : open())}>
        <MoreIcon />
      </button>
      {at && (
        <RowMenu items={items} at={at} label={label} anchorId={id}
                 onClose={() => { setAt(null); btn.current?.focus({ preventScroll: true }); }}
                 onChoose={(id) => items.find((it) => it.id === id)?.onSelect?.()} />
      )}
    </>
  );
}
