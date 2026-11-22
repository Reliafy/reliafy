import { useCallback, useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import Modal from "../components/Modal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { listRcmStudies, createRcmStudy, deleteRcmStudy, getWorkspaceRcm } from "../api.js";
import { rcmDecidedText, rcmTreeRoots } from "../rcmTreeRoots.js";
import { explorerPath } from "../assetTree.js";
import { relativeTime } from "../instrument.js";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";
import "../components/RegisterList.css";

// The RCM section's landing page, its studies: rollup badge strip per study, create modal, free-plan cap
// nudge on 402.
export default function RcmHome() {
  const navigate = useNavigate();
  const [studies, setStudies] = useState(null);
  const [error, setError] = useState(null);
  const [capHit, setCapHit] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [system, setSystem] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  // The RCM done on the asset tree (where a study's decisions drive the tasks): one row per
  // asset, opening its RCM tab. Not offered where the asset tree isn't (the read is refused).
  const [onTree, setOnTree] = useState(null);
  useEffect(() => {
    let on = true;
    getWorkspaceRcm().then((d) => { if (on) setOnTree(rcmTreeRoots(d)); }, () => {});
    return () => { on = false; };
  }, []);

  const [loadError, setLoadError] = useState(null);
  const refresh = useCallback(() => {
    setLoadError(null);
    listRcmStudies()
      .then((d) => setStudies(d.studies || []))
      .catch(setLoadError);
  }, []);
  useEffect(() => refresh(), [refresh]);

  const onCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const study = await createRcmStudy(name.trim(), system.trim(), description.trim());
      navigate(`/maintenance/rcm/${study.id}`);
    } catch (err) {
      if (err.code === "cap") {
        setModalOpen(false);
        setCapHit(true);
      } else {
        setCreateError(err.message);
      }
    } finally {
      setCreating(false);
    }
  };

  const confirm = useConfirm();
  const onDelete = async (s) => {
    if (!(await confirm(deleteOrRemoveConfirm(s, "study", { name: itemName(s) })))) return;
    try {
      await deleteRcmStudy(s.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/maintenance/rcm/${id}`);
  const newStudy = <button onClick={() => { setCreateError(null); setModalOpen(true); }}><PlusIcon /> New study</button>;

  return (
    <div className="app">
      <SectionHeader
        section="maintenance"
        title="RCM studies"
        purpose="Your RCM studies: every maintenance decision links to the analysis behind it, re-checked each time you open the study."
        help={{ guide: "rcm-study" }}
        primary={newStudy}
      />

      {error && <div className="card error">{error}</div>}
      {capHit && (
        <div className="card upgrade-nudge">
          <p>
            You've reached the free-plan limit of 1 RCM study.{" "}
            <Link to="/billing">Upgrade to Pro</Link> for unlimited studies.
          </p>
        </div>
      )}

      {onTree?.length > 0 && (
        <div className="card rcm-on-tree">
          <h2 className="card-title">On your asset tree</h2>
          <p className="lib-date">
            RCM done on the asset tree sets the positions&apos; maintenance tasks directly. Open an asset to carry on there.
          </p>
          <div className="lib maint-scroll">
            <table className="lib-table reg-table rcm-on-tree-table">
              <thead>
                <tr>
                  <th>Position</th>
                  <th className="num">Positions with RCM</th>
                  <th className="num">Failure modes decided</th>
                </tr>
              </thead>
              <tbody>
                {onTree.map((r) => {
                  const to = explorerPath("positions", { sel: r.id, tab: "rcm" });
                  return (
                    <tr key={r.id} className="lib-row" onClick={rowOpen(navigate, to)}>
                      <td>
                        <RowLink to={to} className="lib-name">{r.name || "Unnamed position"}</RowLink>
                        {r.path && <div className="lib-date reg-sub" title={r.path}>{r.path}</div>}
                      </td>
                      <td className="num" data-label="Positions with RCM">{r.positions.toLocaleString("en-AU")}</td>
                      <td className={"num" + (r.modes ? "" : " lib-date")} data-label="Failure modes decided">{rcmDecidedText(r)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <SectionList
        loadError={loadError}
        onRetry={refresh}
        rows={studies}
        noun={["study", "studies"]}
        fields={(s) => [s.name, s.system]}
        empty={{
          title: "No RCM studies yet",
          body: "Create one and build its worksheet: each function, how it fails, what causes the failure, and the decision for each cause.",
          action: newStudy,
        }}
        head={[
          <th key="s" style={{ width: "34%" }}>Study</th>,
          <th key="y" className="lib-opt">System</th>,
          <th key="e">Evidence</th>,
          <th key="u" className="lib-opt">Updated</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(s) => (
          <tr key={s.id} className="lib-row" onClick={() => open(s.id)}>
            <td>
              <div className="lib-name">
                {itemName(s)}
              </div>
            </td>
            <td className="lib-date lib-opt">{s.system || "—"}</td>
            <td>
              {s.rollup?.decided ? (
                <RollupBadges rollup={s.rollup} />
              ) : (
                <span className="lib-date">{s.rollup?.modes ? `${s.rollup.modes} modes` : "Empty"}</span>
              )}
            </td>
            <td className="lib-date lib-opt">{relativeTime(s.updated_at || s.created_at)}</td>
            <RowActions item={s} onOpen={() => open(s.id)} onDelete={() => onDelete(s)} />
          </tr>
        )}
      />

      {modalOpen && (
        <Modal
          title="New RCM study"
          locked={creating}
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button className="secondary" onClick={() => setModalOpen(false)} disabled={creating}>
                Cancel
              </button>
              <button onClick={onCreate} disabled={creating || !name.trim()}>
                {creating ? "Creating…" : "Create study"}
              </button>
            </>
          }
        >
          {createError && <div className="card error">{createError}</div>}
          {onTree !== null && (
            <p className="lib-date">
              A study here stands on its own. To tie the RCM to your equipment (its tasks then go on the positions), start it on the
              asset tree instead: <Link to={explorerPath("positions", { tab: "rcm" })}>open the asset tree&apos;s RCM</Link>.
            </p>
          )}
          <div className="rcm-form">
            <label className="login-field">
              <span>Name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. Conveyor line 2 — RCM"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onCreate()}
              />
            </label>
            <label className="login-field">
              <span>System (optional)</span>
              <input
                type="text"
                value={system}
                placeholder="e.g. Conveyor line 2"
                onChange={(e) => setSystem(e.target.value)}
              />
            </label>
            <label className="login-field">
              <span>Description (optional)</span>
              <textarea
                rows={2}
                value={description}
                placeholder="Scope, operating context, assumptions"
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
          </div>
        </Modal>
      )}
    </div>
  );
}
