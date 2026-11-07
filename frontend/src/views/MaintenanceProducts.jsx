// Products: what you design and build. The landing lists each product (its
// design: a functional structure and the part it is), with the items built from
// it and their open failure reports; a product's page has its tabs: Functional
// structure (the Explorer on its design), Parts list (its part's bill of
// materials), Items (built from it, and Build an item), Failure reports (rolled
// up across the items) and Analysis (its RBDs).
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  addSampleProduct, generatePositionRbd, getPartStructure, getProduct, listProductItems, listProducts, listRbds,
} from "../api.js";
import { SectionHeader, ShowMe } from "../components/SectionPage.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import Tabs from "../components/ui/Tabs.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { fmtDate } from "../components/MaintenanceParts.jsx";
import { RollupCard, StructureTree } from "../components/MaintenanceStructure.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { BuildItemModal, DesignReports, NewProductModal } from "../components/ProductPanels.jsx";
import AssetExplorer from "./AssetExplorer.jsx";
import { SAMPLES, addSample } from "../sampleProduct.js";
import { newPredictionPath } from "../predictions.js";
import {
  PRODUCTS_GUIDE, PRODUCTS_PATH, PRODUCT_TABS, hoursText, itemPagePath, itemTreePath, itemsText, productPath,
  productRbds, productTab, revText,
} from "../products.js";
import "./Maintenance.css";
import "./MaintenanceProducts.css";

const HELP = { guide: PRODUCTS_GUIDE };

// "Add the sample UAV product": once; with a copy there, asked whether to add another.
function useSampleProduct(onAdded) {
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const add = () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    addSample(addSampleProduct, confirm, "product")
      .then((r) => onAdded(r))
      .catch((e) => setError(`The sample product wasn't added: ${e.message}`))
      .finally(() => setBusy(false));
  };
  return { add, busy, error };
}

export default function MaintenanceProducts() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(false);
  useEffect(() => {
    listProducts().then((d) => setRows(d.products || [])).catch((e) => setError(e.message));
  }, []);
  const sample = useSampleProduct((r) => navigate(productPath(r.product?.id || r.position.id)));
  const visible = (rows || []).filter((p) => matches(query, p.name, p.description, p.part?.part_number));
  const newProduct = <button onClick={() => setModal(true)}><PlusIcon /> New product</button>;
  const sampleButton = (
    <button type="button" className="secondary" onClick={sample.add} disabled={sample.busy}>
      {sample.busy ? "Adding…" : SAMPLES.product.label}
    </button>
  );

  return (
    <div className="app">
      <SectionHeader title="Products" purpose="What you design and build: each product's structure, and the items built from it."
                     help={HELP} primary={newProduct}
                     menu={<button type="button" className="ovm-item" onClick={sample.add} disabled={sample.busy}>{SAMPLES.product.label}</button>} />
      {(error || sample.error) && <div className="card error">{error || sample.error}</div>}
      {rows === null ? (
        !error && <div className="card empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card empty section-empty">
          <h2>No products yet</h2>
          <p>A product is a design: what each part of it does (its functional structure, with its FME(C)A and
            RCM) and the part it is, with its bill of materials. Build items from it by serial number; their
            failures roll up to the design.</p>
          <div className="section-empty-action">{newProduct}{sampleButton}</div>
          <p className="section-empty-more"><ShowMe help={HELP}>How products and items work</ShowMe></p>
        </div>
      ) : (
        <>
          <div className="tablebar section-tablebar">
            <span className="count">{query ? `${visible.length} of ${rows.length} products` : `${rows.length} ${rows.length === 1 ? "product" : "products"}`}</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search products…" />
          </div>
          <div className="lib maint-scroll">
            <table className="lib-table pp-table">
              <thead><tr><th>Product</th><th>Revision</th><th className="num">Items built</th><th className="num">Open failure reports</th></tr></thead>
              <tbody>
                {visible.map((p) => (
                  <tr key={p.id} className="lib-row" onClick={() => navigate(productPath(p.id))}>
                    <td>
                      <Link to={productPath(p.id)} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>{p.name}</Link>
                      <div className="lib-date">{[p.part?.part_number && `Part ${p.part.part_number}`,
                        `${p.positions} ${p.positions === 1 ? "position" : "positions"}`].filter(Boolean).join(" · ")}</div>
                    </td>
                    <td data-label="Revision">{p.rev || <span className="lib-date">—</span>}</td>
                    <td className="num" data-label="Items built">{p.items_built > 0
                      ? <Link to={productPath(p.id, "items")} onClick={(e) => e.stopPropagation()}>{p.items_built}</Link>
                      : <span className="lib-date">0</span>}</td>
                    <td className="num" data-label="Open failure reports">{p.open_reports > 0
                      ? <Link to={productPath(p.id, "reports")} onClick={(e) => e.stopPropagation()}>{p.open_reports}</Link>
                      : <span className="lib-date">0</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!visible.length && <p className="section-nomatch">No product matches.</p>}
          </div>
        </>
      )}
      {modal && <NewProductModal onClose={() => setModal(false)} onDone={(p) => navigate(productPath(p.id))} />}
    </div>
  );
}

// ---- one product ------------------------------------------------------------------

export function ProductDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const tab = productTab(params.get("tab"));
  const [product, setProduct] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);
  const [building, setBuilding] = useState(false);
  const [said, setSaid] = useState(null);
  useEffect(() => {
    getProduct(id).then(setProduct).catch((e) => setError(e));
  }, [id, version]);
  const setTab = (t) => navigate(productPath(id, t), { replace: true });

  if (error) {
    return (
      <div className="app">
        <div className="card error">
          {error.status === 404 || error.status === 422 ? "There's no such product (or it's been cleared)." : `The product didn't load: ${error.message}`}
          {" "}<Link to={PRODUCTS_PATH}>Back to Products</Link>
        </div>
      </div>
    );
  }
  if (!product) return <div className="app"><div className="card empty">Loading…</div></div>;

  const header = (
    <div className="app pp-head">
      <PageTitle name={product.name} />
      <PageHeader
        crumbs={[{ label: "Products", to: PRODUCTS_PATH }]}
        title={product.name}
        meta={[revText(product.rev), product.part && `Part ${product.part.part_number}`,
          `${product.positions} ${product.positions === 1 ? "position" : "positions"}`, itemsText(product.items_built) + " built",
          product.open_reports ? `${product.open_reports} open ${product.open_reports === 1 ? "report" : "reports"}` : null]
          .filter(Boolean).join(" · ")}
        id={product.id}
        primary={<button onClick={() => setBuilding(true)}>Build an item</button>}
      />
      {said && <p className="pp-said" role="status">{said}</p>}
      <Tabs tabs={PRODUCT_TABS} value={tab} onChange={setTab} label="Product" className="pp-tabs" />
    </div>
  );
  const built = (out) => {
    setBuilding(false);
    setSaid(`Built ${out.name}: ${out.counts.positions} positions, with the item (serial ${out.serial}) fitted at the top.`);
    setVersion((v) => v + 1);
    navigate(productPath(id, "items"), { replace: true });
  };
  const modal = building && <BuildItemModal product={product} onClose={() => setBuilding(false)} onDone={built} />;

  if (tab === "structure") {
    return (
      <>
        {header}
        <AssetExplorer root={product.id} tabKey="view" title="Functional structure" />
        {modal}
      </>
    );
  }
  return (
    <>
      {header}
      <div className="app pp-body">
        {tab === "parts" && <PartsTab product={product} />}
        {tab === "items" && <ItemsTab product={product} version={version} onBuild={() => setBuilding(true)} />}
        {tab === "reports" && <section className="card"><DesignReports positionId={product.id} /></section>}
        {tab === "analysis" && <AnalysisTab product={product} />}
      </div>
      {modal}
    </>
  );
}

// Parts list: the product's part and what it's made of (Parts and stock's structure).
function PartsTab({ product }) {
  const [structure, setStructure] = useState(null);
  const [error, setError] = useState(null);
  const part = product.part;
  useEffect(() => {
    if (part?.id) getPartStructure(part.id).then(setStructure).catch((e) => setError(e.message));
  }, [part?.id]);
  if (!part) {
    return (
      <section className="card empty">
        <h2>No part yet</h2>
        <p>The parts list is the bill of materials of the product's part. This product has no part yet: make one in
          {" "}<Link to="/asset-register/parts">Parts and stock</Link>, then give it to the product.</p>
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
        {empty ? <p>Nothing inside {part.part_number} yet: add what goes in it on the part's page, or import a BOM in Parts and stock.</p>
          : <StructureTree tree={structure.tree} />}
      </section>
      {!empty && <RollupCard structure={structure} />}
    </>
  );
}

// Items: the items built from the product, and Build an item.
function ItemsTab({ product, version, onBuild }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    listProductItems(product.id).then(setData).catch((e) => setError(e.message));
  }, [product.id, version]);
  if (error) return <div className="card error">The items didn't load: {error}</div>;
  if (!data) return <div className="card empty">Loading…</div>;
  const rows = data.items || [];
  if (!rows.length) {
    return (
      <section className="card empty section-empty">
        <h2>No items built yet</h2>
        <p>Build an item for each serial number: it copies the product's structure into the item's own tree, so
          its fitments, readings and failure reports are its own and roll up here.</p>
        <div className="section-empty-action"><button onClick={onBuild}>Build an item</button></div>
      </section>
    );
  }
  return (
    <section className="card">
      <div className="maint-head">
        <h2>{itemsText(rows.length)} built</h2>
        <button className="secondary sm" onClick={onBuild}>Build an item</button>
      </div>
      <div className="maint-scroll">
        <table className="lib-table pp-table">
          <thead><tr><th>Serial</th><th>Revision</th><th className="num">Hours</th><th>Where</th><th className="num">Open failure reports</th><th>Built</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.top_position_id}>
                <td>{r.item ? <Link to={itemPagePath(r.item.id)}>{r.serial || "(no serial)"}</Link> : (r.serial || "(no serial)")}
                  <div className="lib-date"><Link to={itemTreePath(r.top_position_id)}>Its tree</Link>{!r.item && " · nothing fitted at its top"}</div></td>
                <td data-label="Revision">{r.rev || <span className="lib-date">—</span>}</td>
                <td className="num" data-label="Hours">{hoursText(r.hours)}</td>
                <td data-label="Where" className="lib-date">{r.location?.display || "Not at a location"}</td>
                <td className="num" data-label="Open failure reports">{r.open_reports > 0
                  ? <Link to={`${itemTreePath(r.top_position_id)}&tab=reports`}>{r.open_reports}</Link> : <span className="lib-date">0</span>}</td>
                <td data-label="Built" className="lib-date">{fmtDate(r.built_on)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// Analysis: the product's RBDs (made from its structure, or named after it), and
// Make an RBD from this structure (each top-level part of the design a block).
function AnalysisTab({ product }) {
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
    <section className="card">
      <div className="maint-head">
        <h2>RBDs</h2>
        <button className="secondary sm" onClick={derive} disabled={busy}>{busy ? "Making…" : "Make an RBD from this structure"}</button>
      </div>
      <p className="lib-date">Making one turns each part directly under {product.name} into a block, wired by its connections
        and redundancy groups; a block with no model for its class gets a placeholder, which the RBD says.</p>
      {error && <div className="card error">{error}</div>}
      {rbds === null ? (!error && <p className="lib-date">Loading…</p>) : rbds.length === 0 ? (
        <p>No RBD of this product yet.</p>
      ) : (
        <ul className="pp-links">
          {rbds.map((r) => (
            <li key={r.id}><Link to={`/systems/b/${r.id}`}>{r.name}</Link>
              {r.updated_at && <span className="lib-date"> · updated {fmtDate(String(r.updated_at).slice(0, 10))}</span>}</li>
          ))}
        </ul>
      )}
      <p className="lib-date">Models fitted to a design position's pooled life data, and requirements on the design, aren't here yet.</p>
      <div className="maint-head" style={{ marginTop: "var(--sp-4)" }}>
        <h2>Reliability prediction</h2>
        <button type="button" className="secondary sm" onClick={() => navigate(newPredictionPath({ product: product.id }))}>
          New prediction from its parts list
        </button>
      </div>
      <p className="lib-date">A parts count: the parts list's lowest-level parts, each given a handbook part type, added up from
        handbook base rates for the environment the product works in. For a design with no failure data yet.</p>
    </section>
  );
}
