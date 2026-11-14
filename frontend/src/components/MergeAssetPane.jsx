import { useEffect, useMemo, useState } from "react";
import { getMaintenanceTree, listMaintenancePlaces, updateMaintenanceLocation, updateMaintenancePosition } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { mergeChange, mergeCounts, mergeSentence, mergeSpots, mergeTargets } from "../assetMerge.js";
import TablePane from "./TablePane.jsx";
import "../views/Maintenance.css";
import "./MergeAssetPane.css";

// Merge into another asset… (the asset's top row menu in the Explorer, or its row menu on the Assets
// list): in the Explorer's table area beside the tree, not a dialog. Pick the asset it joins, then
// where in that asset's tree it goes, read what will happen, then Merge. Everything inside it comes
// along with its history (assetMerge.js: the tree's own move). Make this its own asset… undoes it.
//
//   source    {id, name, kind: "place" | "unit"}: the asset open
//   data      the Explorer's tree of it (what comes along is counted from it)
//   onDone({target, spot, text})  merged: the Explorer opens the target with the merged part picked
//   readOnly  the reason the workspace can't be changed (view only), or null
//   phone, headingRef, onClose: TablePane's
export default function MergeAssetPane({ source, data, onDone, readOnly = null, phone = false, headingRef = null, onClose }) {
  const [places, setPlaces] = useState(null);
  const [listError, setListError] = useState(null);
  const [assetQuery, setAssetQuery] = useState("");
  const [target, setTarget] = useState(null);
  const [tree, setTree] = useState(null);
  const [treeError, setTreeError] = useState(null);
  const [spotQuery, setSpotQuery] = useState("");
  const [spot, setSpot] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);

  useEffect(() => {
    let live = true;
    listMaintenancePlaces().then((v) => live && setPlaces(v.places || []), (e) => live && setListError(e.message || "Couldn't load the assets."));
    return () => { live = false; };
  }, []);
  // The target's own tree (nothing of any other asset), read once it's picked.
  useEffect(() => {
    if (!target) return undefined;
    let live = true;
    setTree(null);
    setTreeError(null);
    getMaintenanceTree({ within: target.id })
      .then((t) => live && setTree(t), (e) => live && setTreeError(e.message || "Couldn't load that asset's tree."));
    return () => { live = false; };
  }, [target]);

  const targets = useMemo(() => mergeTargets(places, source.id, assetQuery), [places, source.id, assetQuery]);
  const spots = useMemo(() => mergeSpots(tree, source.kind, spotQuery), [tree, source.kind, spotQuery]);
  const counts = useMemo(() => mergeCounts(data, source.kind), [data, source.kind]);
  const change = mergeChange(source.kind, source.id, spot);
  const sentence = target && spot ? mergeSentence(source.name, counts, target, spot) : null;
  const pickTarget = (p) => {
    setTarget(p);
    setSpot(null);
    setSpotQuery("");
    setFailed(null);
  };

  const merge = async () => {
    if (!change || busy) return;
    setBusy(true);
    setFailed(null);
    try {
      if (change.kind === "location") await updateMaintenanceLocation(change.id, change.body);
      else await updateMaintenancePosition(change.id, change.body);
      onDone?.({ target, spot, text: `Merged. ${source.name || "(no name)"} is part of ${target.name || "(no name)"} now.` });
    } catch (e) {
      setFailed(saveErrorText(e, { what: "merge it", offline: navigator.onLine === false }));
      setBusy(false);
    }
  };

  const pick = (fn) => ({
    onClick: fn,
    onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } },
  });
  const kindWord = source.kind === "place" ? "a location" : "a location or a position";

  return (
    <TablePane title="Merge into another asset" subject={source.name || "(no name)"} phone={phone} busy={busy}
               headingRef={headingRef} onClose={onClose} className="merge-pane">
      <div className="merge-asset">
        <p className="rim-tquiet ma-intro">
          {source.name || "This asset"} becomes part of another asset, with everything inside it: history, readings,
          tasks, RCM and what&apos;s fitted all come along. To split it off again, use <b>Make this its own asset…</b> on
          its row there.
        </p>
        {readOnly && <p className="rim-tquiet" role="note">{readOnly}</p>}

        <section className="ma-step" aria-labelledby="ma-target">
          <h3 id="ma-target" className="ma-title">1. The asset it joins</h3>
          <input type="search" value={assetQuery} onChange={(e) => setAssetQuery(e.target.value)} placeholder="Search assets…"
                 aria-label="Search assets" className="ma-search" />
          {listError && <p className="field-error" role="alert">{listError}</p>}
          {places === null && !listError ? <p className="lib-date">Loading the assets…</p> : (
            <ul className="rcm-move-tree ma-list" role="listbox" aria-label="Assets">
              {targets.map((p) => (
                <li key={p.id} role="option" aria-selected={target?.id === p.id} tabIndex={0}
                    className={"rcm-mt-row" + (target?.id === p.id ? " picked" : "")} {...pick(() => pickTarget(p))}>
                  <span className="rcm-mt-name">{p.name || "(no name)"}
                    {p.positions ? <span className="lib-date"> · {p.positions} position{p.positions === 1 ? "" : "s"}</span> : null}</span>
                </li>
              ))}
            </ul>
          )}
          {places && !targets.length && (
            <p className="lib-date">{assetQuery.trim() ? "No asset matches that." : "There's no other asset to merge into. Add one on Assets first."}</p>
          )}
        </section>

        {target && (
          <section className="ma-step" aria-labelledby="ma-spot">
            <h3 id="ma-spot" className="ma-title">2. Where it goes in {target.name || "(no name)"}</h3>
            <p className="rim-tquiet">Pick {kindWord} in {target.name || "that asset"}.</p>
            <input type="search" value={spotQuery} onChange={(e) => setSpotQuery(e.target.value)} placeholder="Name, tag or a row above it"
                   aria-label={`Search ${target.name || "the asset"}`} className="ma-search" />
            {treeError && <p className="field-error" role="alert">{treeError}</p>}
            {tree === null && !treeError ? <p className="lib-date">Loading its tree…</p> : (
              <ul className="rcm-move-tree ma-list" role="listbox" aria-label={`Where in ${target.name || "the asset"}`}>
                {spots.rows.map((r) => (
                  <li key={`${r.kind}:${r.id}`} role="option" aria-selected={spot?.id === r.id} tabIndex={0}
                      className={"rcm-mt-row" + (spot?.id === r.id ? " picked" : "")}
                      style={{ paddingLeft: 4 + Math.min(spotQuery.trim() ? 0 : r.depth, 12) * 16 }}
                      {...pick(() => { setSpot(r); setFailed(null); })}>
                    <span className="rcm-mt-name">
                      {spotQuery.trim() && r.path.length ? <span className="lib-date">{r.path.join(" › ")} › </span> : null}
                      {r.name}{r.tag ? <span className="lib-date"> · {r.tag}</span> : null}
                    </span>
                    <span className="rcm-mt-here">{r.kind === "pos" ? "Position" : "Location"}</span>
                  </li>
                ))}
              </ul>
            )}
            {tree && !spots.rows.length && <p className="lib-date">{spotQuery.trim() ? "Nothing matches that." : `${target.name || "That asset"} has nowhere it can go yet.`}</p>}
            {spots.more && <p className="lib-date">Showing the first rows: type to narrow the list.</p>}
          </section>
        )}

        <p className="ma-say" role="status" aria-live="polite">
          {sentence || (target ? "Pick where it goes." : "Pick the asset it joins.")}
        </p>
        {failed && <p className="field-error" role="alert">{failed}</p>}
        <div className="ma-actions">
          <button type="button" onClick={merge} disabled={!change || busy || !!readOnly} aria-busy={busy || undefined}>
            {busy ? "Merging…" : "Merge"}
          </button>
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
        </div>
      </div>
    </TablePane>
  );
}
