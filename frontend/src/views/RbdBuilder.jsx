import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import RbdEditor, { SAMPLE_SUFFIX } from "../components/RbdEditor.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import Chip from "../components/ui/Chip.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { safetyStarter } from "../rbdSafetyStarter.js";
import { RBDS_LABEL, RBDS_PATH } from "../navigation.js";

// Design › Systems › an RBD (/systems/b/:id, /systems/b for a new one): the page around the RBD
// editor. The editor itself (components/RbdEditor.jsx) is the one the Explorer's table area shows
// for a position's RBD, so a change to the builder is a change to both. This page adds what only
// a page has: its title and header (Share, Copy ID), the notes for an imported diagram, a starter
// or a model just added, the address following a save, and "Diagram not found".

export default function RbdBuilder() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // An imported diagram, or the safety function starter (#298), opens unsaved.
  const starterKind = id ? null : location.state?.starter || null;
  const starter = useMemo(() => (starterKind === "safety" ? safetyStarter() : null),
    // A fresh copy each time the starter is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [starterKind, location.key]);
  const imported = id ? null : location.state?.imported || starter;
  const [notesHidden, setNotesHidden] = useState(false);
  // A model's "Add to an RBD" (#294): its block, added once; the route's
  // state is dropped so a reload doesn't add it again.
  const addModel = location.state?.addModel || null;
  const [added, setAdded] = useState(null); // { name, wired }
  const onModelAdded = useCallback((name, wired) => {
    setAdded({ name, wired });
    navigate(location.pathname, { replace: true, state: null });
  }, [navigate, location.pathname]);
  // Opened from a fault tree's "Open as RBD": what the conversion noted, shown once above the diagram.
  const [fromTree] = useState(() => (id ? location.state?.fromFaultTree || null : null));
  const [fromTreeHidden, setFromTreeHidden] = useState(false);
  const [meta, setMeta] = useState({});
  const [tab, setTab] = useState("builder");
  const [loadError, setLoadError] = useState(null); // { id, missing, message }
  const onLoadError = useCallback((err) => setLoadError({
    id, missing: err?.status === 404 || err?.status === 403, message: err?.message,
  }), [id]);
  // One Builder per diagram opened: a new route gets a fresh one, but the
  // route catching up with the Builder's own save (a new diagram's first
  // save, or Save as new) keeps it, so the canvas, its view and full screen
  // carry on as they were.
  const routeKey = id || (starter ? `starter-${location.key}` : "new");
  const keyRef = useRef({ route: routeKey, gen: 0, savedId: null });
  const keys = keyRef.current;
  if (keys.route !== routeKey) {
    if (!(id && id === keys.savedId)) keys.gen += 1;
    keys.route = routeKey;
    keys.savedId = null;
  }
  if (loadError && loadError.id === id) {
    return (
      <div className="app">
        <PageTitle name={loadError.missing ? "Diagram not found" : "Couldn't open this diagram"} />
        <PageHeader crumbs={[{ label: RBDS_LABEL, to: RBDS_PATH }]}
                    title={loadError.missing ? "Diagram not found" : "Couldn't open this diagram"} />
        <div className="card" role="alert">
          <p style={{ marginTop: 0 }}>
            {loadError.missing
              ? "There's no diagram at this address. It may have been deleted, or the link may be mistyped."
              : `Something stopped the diagram loading: ${loadError.message || "an unknown error"}. Try again in a moment.`}
          </p>
          <p style={{ marginBottom: 0 }}>
            <Link to={RBDS_PATH}>See your RBDs</Link> · <Link to="/systems/b">Start a new diagram</Link>
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className={"app rbd-app" + (tab === "builder" ? "" : " rbd-app-scroll")}>
      <PageTitle name={(meta.name || "").replace(SAMPLE_SUFFIX, "")} />
      <PageHeader
        className="rbd-header"
        crumbs={[{ label: RBDS_LABEL, to: RBDS_PATH }]}
        title={(meta.name || "").replace(SAMPLE_SUFFIX, "") || (id ? "" : "Untitled RBD")}
        badges={SAMPLE_SUFFIX.test(meta.name || "") && <Chip>Sample</Chip>}
        id={meta.id || id}
        menu={meta.id && (
          <ShareButton
            collection="rbds"
            artifactId={meta.id}
            name={meta.name || "Untitled RBD"}
            readOnly={meta.readOnly}
            className="ovm-item"
          />
        )}
      />
      {imported && !notesHidden && (
        <div className="card note rbd-import-note">
          {imported.starter ? (
            <p>
              <b>A starter safety function</b> — not saved yet. Calculate it as it is, or rename the blocks and set
              each one’s λDU and proof test to your loop’s, then Save.
              {" "}<button className="link" onClick={() => setNotesHidden(true)}>Dismiss</button>
            </p>
          ) : (
            <p>
              <b>Imported from {imported.source_format || "file"}</b> — not saved yet. Check the blocks, then Save to keep it.
              {" "}<button className="link" onClick={() => setNotesHidden(true)}>Dismiss</button>
            </p>
          )}
          {imported.warnings?.length > 0 && (
            <ul>
              {imported.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
        </div>
      )}
      {fromTree && !fromTreeHidden && (
        <div className="card note rbd-import-note">
          <p>
            <b>Made from the fault tree “{fromTree.tree}”</b> and saved. It doesn't follow later edits to the tree.
            {" "}<button className="link" onClick={() => setFromTreeHidden(true)}>Dismiss</button>
          </p>
          {fromTree.notes?.length > 0 && <ul>{fromTree.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        </div>
      )}
      {added && (
        <div className="card note rbd-import-note">
          <p>
            <b>“{added.name}” added as a block</b> — not saved yet.{" "}
            {added.wired
              ? "Calculate it as it is, or add the rest of the system, then Save."
              : "It sits below the others: wire it in where it belongs, then Save."}
            {" "}<button className="link" onClick={() => setAdded(null)}>Dismiss</button>
          </p>
        </div>
      )}
      <RbdEditor
        key={`builder-${keys.gen}`}
        rbdId={id}
        imported={imported}
        onSaved={(savedId) => {
          keyRef.current.savedId = savedId;
          // Saved: the "added as a block — not saved yet" note no longer holds.
          setAdded(null);
          navigate(`/systems/b/${savedId}`, { replace: true });
        }}
        onMeta={setMeta}
        onTab={setTab}
        addModel={addModel}
        onModelAdded={onModelAdded}
        onLoadError={onLoadError}
      />
    </div>
  );
}
