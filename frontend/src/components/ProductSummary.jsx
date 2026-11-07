// A product's own row in the Explorer (its page, /products/:id, is the
// Explorer on its design): the Summary panel holds what the product page's
// header and tabs held. Facts (revision, part, positions, items built, open
// reports) in place of an asset's (nothing is fitted to a design or kept
// anywhere); Build an item; the items built from it; their failure reports
// rolled up; and the analyses of the design (its RBDs, a reliability
// prediction). The parts list is the tree's Parts tab (ProductPartsList at the
// top of it).
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { generatePositionRbd, getPartStructure, getProduct, listProductItems, listRbds } from "../api.js";
import Section from "./ui/Section.jsx";
import { fmtDate } from "./MaintenanceParts.jsx";
import { RollupCard, StructureTree } from "./MaintenanceStructure.jsx";
import { BuildItemModal, DesignReports } from "./ProductPanels.jsx";
import TreeSummary from "./TreeSummary.jsx";
import { newPredictionPath } from "../predictions.js";
import {
  ITEMS_PATH, hoursText, itemPagePath, itemTreePath, itemsText, productRbds, revText,
} from "../products.js";
import "../views/MaintenanceProducts.css";

const quiet = (text) => <span className="td-quiet">{text}</span>;

function useProduct(id, version) {
  const [state, setState] = useState({ id: null, product: null, error: null });
  useEffect(() => {
    let live = true;
    getProduct(id).then((product) => live && setState({ id, product, error: null }))
      .catch((e) => live && setState({ id, product: null, error: e.message }));
    return () => { live = false; };
  }, [id, version]);
  return state.id === id ? state : { id, product: null, error: null };
}

function ProductFacts({ product }) {
  const rows = [
    ["Revision", product.rev ? revText(product.rev) : quiet("None")],
    ["Part", product.part ? <><Link to={`/asset-register/parts/${product.part.id}`}>{product.part.part_number}</Link>
      <span className="td-quiet td-sub">{product.part.name}</span></> : quiet("No part yet")],
    ["Positions", Number(product.positions || 0).toLocaleString("en-AU")],
    ["Items built", itemsText(product.items_built)],
    ["Open failure reports", product.open_reports ? Number(product.open_reports).toLocaleString("en-AU") : quiet("None")],
  ];
  return (
    <Section title="Facts">
      <dl className="td-kv">
        {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
    </Section>
  );
}

// The items built from the product: serial, revision, hours, where, open reports.
function BuiltItems({ product, version, onBuild }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    listProductItems(product.id).then(setData).catch((e) => setError(e.message));
  }, [product.id, version]);
  const rows = data?.items || [];
  return (
    <Section title="Built items" count={rows.length || null} id="built-items"
             action={{ label: "Build an item…", onClick: onBuild }}>
      {error ? <p className="field-error" role="alert">The items didn't load: {error}</p>
        : !data ? <p className="td-quiet">Loading…</p>
        : rows.length === 0 ? (
          <p className="td-quiet">No items built yet. Build one for each serial number: it copies this structure into the
            item's own tree, so its fitments, readings and failure reports are its own and roll up here.</p>
        ) : (
          <div className="maint-scroll">
            <table className="lib-table pp-table">
              <thead><tr><th>Serial</th><th>Revision</th><th className="num">Hours</th><th>Where</th><th className="num">Open failure reports</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.top_position_id}>
                    <td>{r.item ? <Link to={itemPagePath(r.item.id)}>{r.serial || "(no serial)"}</Link> : (r.serial || "(no serial)")}
                      <div className="lib-date"><Link to={itemTreePath(r.top_position_id)}>Its tree</Link>
                        {r.built_on && ` · built ${fmtDate(r.built_on)}`}</div></td>
                    <td data-label="Revision">{r.rev || <span className="lib-date">—</span>}</td>
                    <td className="num" data-label="Hours">{hoursText(r.hours)}</td>
                    <td data-label="Where" className="lib-date">{r.location?.display || "Not at a location"}</td>
                    <td className="num" data-label="Open failure reports">{r.open_reports > 0
                      ? <Link to={`${itemTreePath(r.top_position_id)}&tab=reports`}>{r.open_reports}</Link> : <span className="lib-date">0</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      <Link className="td-more" to={ITEMS_PATH}>Every item, on Items</Link>
    </Section>
  );
}

// The analyses of the design: its RBDs (made from its structure, or named
// after it), Make an RBD from this structure, and a reliability prediction.
function Analyses({ product }) {
  const navigate = useNavigate();
  const [rbds, setRbds] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    listRbds().then((d) => setRbds(productRbds(product, d.rbds || []))).catch((e) => setError(e.message));
  }, [product]);
  const derive = () => {
    setBusy(true);
    setError(null);
    generatePositionRbd(product.id)
      .then((r) => navigate(`/systems/b/${r.rbd_id}`))
      .catch((e) => { setError(`The RBD wasn't made: ${e.message}`); setBusy(false); });
  };
  return (
    <Section title="Analyses of this design" count={rbds?.length || null} id="design-analysis">
      {error && <p className="field-error" role="alert">{error}</p>}
      {rbds === null ? (!error && <p className="td-quiet">Loading…</p>) : rbds.length === 0 ? (
        <p className="td-quiet">No RBD of this product yet.</p>
      ) : (
        <ul className="pp-links">
          {rbds.map((r) => (
            <li key={r.id}><Link to={`/systems/b/${r.id}`}>{r.name}</Link>
              {r.updated_at && <span className="lib-date"> · updated {fmtDate(String(r.updated_at).slice(0, 10))}</span>}</li>
          ))}
        </ul>
      )}
      <div className="maint-row">
        <button type="button" className="secondary sm" onClick={derive} disabled={busy}>{busy ? "Making…" : "Make an RBD from this structure"}</button>
        <button type="button" className="secondary sm" onClick={() => navigate(newPredictionPath({ product: product.id }))}>
          New prediction from its parts list
        </button>
      </div>
      <p className="td-quiet">Making an RBD turns each part directly under {product.name} into a block, wired by its connections
        and redundancy groups; a block with no model for its class gets a placeholder, which the RBD says. A prediction is
        a parts count from handbook base rates, for a design with no failure data yet.</p>
    </Section>
  );
}

// The product's own row: its Summary.
export default function ProductSummary({ row, version: treeVersion = 0, ...props }) {
  const [version, setVersion] = useState(0);
  const [building, setBuilding] = useState(false);
  const [said, setSaid] = useState(null);
  const { product, error } = useProduct(row.key, `${treeVersion}:${version}`);
  const built = useCallback((out) => {
    setBuilding(false);
    setSaid(`Built ${out.name}: ${out.counts.positions} positions, with the item (serial ${out.serial}) fitted at the top.`);
    setVersion((v) => v + 1);
  }, []);
  const facts = error ? <p className="field-error" role="alert">The product didn't load: {error}</p>
    : product ? <ProductFacts product={product} /> : <p className="td-quiet">Loading…</p>;
  return (
    <>
      <TreeSummary row={row} {...props} design facts={facts}>
        {said && <p className="pp-said" role="status">{said}</p>}
        {product && (
          <>
            <BuiltItems product={product} version={version} onBuild={() => setBuilding(true)} />
            <Section title="Failure reports on the built items" count={product.open_reports || null} id="design-reports"
                     tip="A report is about an item, filed on its tree; here they roll up to the design.">
              <DesignReports positionId={product.id} />
            </Section>
            <Analyses product={product} />
          </>
        )}
      </TreeSummary>
      {building && product && <BuildItemModal product={product} onClose={() => setBuilding(false)} onDone={built} />}
    </>
  );
}

// The product's parts list: its part and what it's made of (the top of the
// Parts tab on the product's own row).
export function ProductPartsList({ productId }) {
  const { product, error: productError } = useProduct(productId, 0);
  const [structure, setStructure] = useState(null);
  const [error, setError] = useState(null);
  const part = product?.part;
  useEffect(() => {
    if (part?.id) getPartStructure(part.id).then(setStructure).catch((e) => setError(e.message));
  }, [part?.id]);
  if (productError) return <div className="card error">The product didn't load: {productError}</div>;
  if (!product) return <div className="card empty">Loading…</div>;
  if (!part) {
    return (
      <section className="card empty">
        <h2>No part yet</h2>
        <p>The parts list is the bill of materials of the product's part. This product has no part yet: make one with
          {" "}New part below, then give it to the product.</p>
      </section>
    );
  }
  if (error) return <div className="card error">The parts list didn't load: {error}</div>;
  if (!structure) return <div className="card empty">Loading…</div>;
  const empty = !(structure.tree?.children || []).length;
  return (
    <>
      <section className="card">
        <div className="maint-head">
          <h2>Parts list</h2>
          <Link to={`/asset-register/parts/${part.id}`}>Change it on {part.part_number}'s page</Link>
        </div>
        <p className="lib-date">As designed: the structure of the product's part, {part.part_number} ({part.name}).</p>
        {empty ? <p>Nothing inside {part.part_number} yet: add what goes in it on the part's page, or import a BOM below.</p>
          : <div className="maint-scroll"><StructureTree tree={structure.tree} /></div>}
      </section>
      {!empty && <RollupCard structure={structure} />}
    </>
  );
}
