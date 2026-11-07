// Items: every serial-numbered thing in the workspace, built from a product or
// not: its product, type (item class), where it is, its status and open failure
// reports. Filters by product and type, and a search, go to the server
// (GET /api/maintenance/items/overview); each row opens the item's page, and
// "Its tree" the Explorer on the tree it heads or sits in.
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getItemClasses, listItemsOverview, listProducts } from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import ListSearch from "../components/ListSearch.jsx";
import { ClassPicker } from "../components/MaintenanceItemClasses.jsx";
import { explorerPath } from "../assetTree.js";
import {
  PRODUCTS_GUIDE, PRODUCTS_PATH, itemFilters, itemPagePath, itemTreePath, productPath, statusText,
} from "../products.js";
import "./Maintenance.css";
import "./MaintenanceProducts.css";

const LIMIT = 500;

// Where a row's tree link goes: its built tree, else the tree it's fitted in.
const treeOf = (it) => (it.top_position_id ? itemTreePath(it.top_position_id)
  : it.position ? explorerPath("positions", { sel: it.position.id }) : null);

export default function MaintenanceItemsList() {
  const navigate = useNavigate();
  const [products, setProducts] = useState([]);
  const [classes, setClasses] = useState([]);
  const [productId, setProductId] = useState("");
  const [classId, setClassId] = useState(null);
  const [query, setQuery] = useState("");
  const [sent, setSent] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    listProducts().then((d) => setProducts(d.products || [])).catch(() => {});
    getItemClasses().then((d) => setClasses(d.classes || [])).catch(() => {});
  }, []);
  // The search goes a moment after typing stops.
  useEffect(() => {
    const t = setTimeout(() => setSent(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => {
    let live = true;
    setError(null);
    listItemsOverview({ productId, itemClassId: classId, q: sent, limit: LIMIT })
      .then((d) => live && setData(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [productId, classId, sent]);

  const items = data?.items || [];
  const filtered = !!(productId || classId || sent);
  const empty = data && !filtered && data.total === 0;

  return (
    <div className="app">
      <SectionHeader title="Items" purpose="Every serial-numbered thing: what it is, where it is, and its open failure reports."
                     help={{ guide: PRODUCTS_GUIDE }} primary={<button onClick={() => navigate(PRODUCTS_PATH)}>Build from a product</button>} />
      {error && <div className="card error">The items didn't load: {error}</div>}
      {!data ? (
        !error && <div className="card empty">Loading…</div>
      ) : empty ? (
        <div className="card empty section-empty">
          <h2>No items yet</h2>
          <p>An item is one physical thing with a serial number and its own history. Build one from a product, or
            fit one to a position in your assets.</p>
          <div className="section-empty-action">
            <button onClick={() => navigate(PRODUCTS_PATH)}>Go to Products</button>
            <button className="secondary" onClick={() => navigate(explorerPath("positions"))}>Go to the Explorer</button>
          </div>
        </div>
      ) : (
        <>
          <div className="tablebar section-tablebar pp-filters">
            <span className="count">{filtered ? `${data.total} ${data.total === 1 ? "match" : "matches"}` : `${data.total} ${data.total === 1 ? "item" : "items"}`}</span>
            <label className="pp-filter"><span className="sr-only">Product</span>
              <select value={productId} onChange={(e) => setProductId(e.target.value)} aria-label="Product">
                <option value="">Any product</option>
                {itemFilters(products).products.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                <option value="none">No product</option>
              </select>
            </label>
            <label className="pp-filter"><span className="sr-only">Type</span>
              <ClassPicker classes={classes} value={classId} onChange={setClassId} emptyLabel="Any type" />
            </label>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search name, serial, part…" />
          </div>
          <div className="lib maint-scroll">
            <table className="lib-table pp-table">
              <thead><tr><th>Item</th><th>Product</th><th>Type</th><th>Where</th><th>Status</th><th className="num">Open failure reports</th></tr></thead>
              <tbody>
                {items.map((it) => {
                  const tree = treeOf(it);
                  return (
                    <tr key={it.id} className="lib-row" onClick={() => navigate(itemPagePath(it.id))}>
                      <td>
                        <Link to={itemPagePath(it.id)} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>{it.name || "(no name)"}</Link>
                        <div className="lib-date">{[it.serial && `Serial ${it.serial}`, it.part_number && `Part ${it.part_number}`].filter(Boolean).join(" · ")}
                          {tree && <>{(it.serial || it.part_number) ? " · " : ""}<Link to={tree} onClick={(e) => e.stopPropagation()}>Its tree</Link></>}</div>
                      </td>
                      <td data-label="Product">{it.product
                        ? <Link to={productPath(it.product.id)} onClick={(e) => e.stopPropagation()}>{it.product.name}</Link>
                        : <span className="lib-date">—</span>}</td>
                      <td data-label="Type">{it.item_class?.name || <span className="lib-date">—</span>}</td>
                      <td data-label="Where" className="lib-date">{it.position?.path || it.location?.display || "—"}</td>
                      <td data-label="Status">{statusText(it.status)}{it.out_of_service && <div className="maint-overdue">out of service</div>}</td>
                      <td className="num" data-label="Open failure reports">{it.open_reports || <span className="lib-date">0</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!items.length && <p className="section-nomatch">No item matches.</p>}
            {data.total > items.length && <p className="lib-date">Showing the first {items.length} of {data.total}: search or filter to narrow it.</p>}
          </div>
        </>
      )}
    </div>
  );
}
