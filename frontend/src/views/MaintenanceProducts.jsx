// Products: what you design and build. The landing lists each product (its
// design: a functional structure and the part it is), with the items built
// from it and their open failure reports: the same page as Assets
// (RegisterList), with the design's columns. A product's page is the Explorer
// on its design, laid out as Assets › Explorer is: the tree with the panel
// beside it. The product's own row's Summary holds its facts, Build an item,
// the items built, their failure reports and its analyses (ProductSummary);
// the parts list is the tree's Parts tab. A design has no maintenance done to
// it: no failure reports, signals or stock on its rows (explorerTabs.js).
import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { addSampleProduct, getProduct, listProducts } from "../api.js";
import RegisterList, { CountCell } from "../components/RegisterList.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { NewProductModal } from "../components/ProductPanels.jsx";
import { DeleteTreeModal, DeletedToast } from "../components/DeleteTree.jsx";
import AssetExplorer from "./AssetExplorer.jsx";
import { SAMPLES, addSample } from "../sampleProduct.js";
import { PRODUCTS_GUIDE, PRODUCTS_PATH, productPath, productTab } from "../products.js";
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
  const [modal, setModal] = useState(false);
  const reload = useCallback(() => {
    listProducts().then((d) => setRows(d.products || [])).catch((e) => setError(e.message));
  }, []);
  useEffect(() => reload(), [reload]);
  // Delete… on a row (or on a product's own tree, arriving here): its design
  // with everything inside it ({id, name}), then the toast with Undo. Items
  // built from it stay.
  const [deleting, setDeleting] = useState(null);
  const location = useLocation();
  const [deleted, setDeleted] = useState(() => location.state?.deleted || null);
  useEffect(() => {
    // Shown once: a reload of the page doesn't bring the toast back.
    if (location.state?.deleted) navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const sample = useSampleProduct((r) => navigate(productPath(r.product?.id || r.position.id)));
  const newProduct = <button onClick={() => setModal(true)}><PlusIcon /> New product</button>;
  const sampleButton = (
    <button type="button" className="secondary" onClick={sample.add} disabled={sample.busy}>
      {sample.busy ? "Adding…" : SAMPLES.product.label}
    </button>
  );
  const n = (rows || []).length;
  const columns = [
    { key: "rev", label: "Revision", cell: (p) => p.rev || <span className="lib-date">—</span> },
    {
      key: "built", label: "Items built", num: true,
      cell: (p) => <CountCell n={p.items_built} to={productPath(p.id)} label={`${p.items_built} items built from ${p.name}`} />,
    },
    {
      key: "reports", label: "Open failure reports", num: true,
      cell: (p) => <CountCell n={p.open_reports} to={productPath(p.id)} label={`${p.open_reports} open failure reports on ${p.name}`} />,
    },
  ];

  return (
    <>
      <RegisterList
        title="Products" purpose="What you design and build: each product's structure, and the items built from it."
        help={HELP} primary={newProduct}
        menu={<button type="button" className="ovm-item" onClick={sample.add} disabled={sample.busy}>{SAMPLES.product.label}</button>}
        error={error || sample.error} rows={rows} noun={["product", "products"]}
        count={`${n} ${n === 1 ? "product" : "products"}`}
        search={(p) => [p.name, p.description, p.part?.part_number]}
        name={(p) => ({
          to: productPath(p.id), label: p.name,
          sub: [p.description, p.part?.part_number && `Part ${p.part.part_number}`,
            `${p.positions} ${p.positions === 1 ? "position" : "positions"}`].filter(Boolean).join(" · "),
        })}
        columns={columns} onDelete={setDeleting}
        empty={{
          title: "No products yet",
          text: "A product is a design: what each part of it does (its functional structure, with its FME(C)A and RCM) and the part it is, with its bill of materials. Build items from it by serial number; their failures roll up to the design.",
          sample: sampleButton,
          guide: "How products and items work",
        }}
      />
      {modal && <NewProductModal onClose={() => setModal(false)} onDone={(p) => navigate(productPath(p.id))} />}
      {deleting && (
        <DeleteTreeModal kind="position" id={deleting.id} name={deleting.name} onClose={() => setDeleting(null)}
                         onDone={(answer, done) => { setDeleting(null); setDeleted(done); reload(); }} />
      )}
      {deleted && <DeletedToast key={deleted.id} deleted={deleted} onClose={() => setDeleted(null)} onRestored={reload} />}
    </>
  );
}

// ---- one product ------------------------------------------------------------------

// A product's page: the Explorer on its design, the tree's title the product's
// name. ?view= names the tree's tab (?view=fmea); an earlier page tab (?tab=)
// lands on the tree's Parts tab or the product's Summary.
export function ProductDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [product, setProduct] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    setProduct(null);
    setError(null);
    getProduct(id).then(setProduct).catch((e) => setError(e));
  }, [id]);
  const legacy = params.get("tab");
  useEffect(() => {
    if (legacy == null) return;
    setParams((q) => {
      const next = new URLSearchParams(q);
      next.delete("tab");
      const view = productTab(legacy);
      if (view && !next.get("view")) next.set("view", view);
      return next;
    }, { replace: true });
  }, [legacy, setParams]);

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
  return (
    <>
      <PageTitle name={product.name} />
      <AssetExplorer key={id} root={product.id} tabKey="view" title={product.name} heading={1} />
    </>
  );
}
