import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getAltModel, getDegradationModel, getJointModel, getModel, getRecurrentModel } from "../api.js";
import { firstFound, modelPage, otherModelPage, otherPages } from "../modelRoute.js";

const GETTERS = {
  life: getModel,
  recurrent: getRecurrentModel,
  alt: getAltModel,
  degradation: getDegradationModel,
  joint: getJointModel,
};

// A model page whose id its own list doesn't know (404). Another kind's id
// (an old link, a hand-typed address) goes to that model's own page; an id no
// list knows says so plainly, with links back, instead of a bare "Model not
// found.".
export default function ModelNotFound({ id, kind }) {
  const navigate = useNavigate();
  const [state, setState] = useState("looking"); // looking | missing | { label, to }
  useEffect(() => {
    let live = true;
    const pages = otherPages(kind);
    Promise.allSettled(pages.map((p) => GETTERS[p.key](id))).then((settled) => {
      if (!live) return;
      // The non-repairable list also answers for condition and life models.
      const i = pages.findIndex((p) => p.key === "life");
      const life = i >= 0 && settled[i].status === "fulfilled" ? settled[i].value : null;
      const viaLife = life && otherModelPage(life);
      const found = viaLife || firstFound(id, pages, settled);
      if (found) {
        setState(found);
        navigate(found.to, { replace: true });
      } else setState("missing");
    });
    return () => { live = false; };
  }, [id, kind, navigate]);

  const own = modelPage(kind);
  if (state === "looking") {
    return <div className="mf-body mf-single"><p className="muted-line">Looking for this model…</p></div>;
  }
  if (state !== "missing") {
    return (
      <div className="mf-body mf-single">
        <div className="card">This is a {state.label} model. <Link to={state.to}>Open it</Link></div>
      </div>
    );
  }
  return (
    <div className="mf-body mf-single">
      <div className="card" role="alert">
        <p style={{ marginTop: 0 }}>We couldn't find this model. It may have been deleted, or the link may be mistyped.</p>
        <p style={{ marginBottom: 0 }}>
          {own && <><Link to={own.list}>See your {own.listLabel.toLowerCase()}</Link> · </>}
          <Link to="/models">All models</Link>
        </p>
      </div>
    </div>
  );
}

// A saved model this page can't draw (an error while rendering its results):
// a small card in the page, not the whole-app error page. The error is still
// reported by the ErrorBoundary around it.
export function ModelDrawFailed() {
  return (
    <div className="mf-body mf-single">
      <div className="card error" role="alert">
        <p style={{ marginTop: 0 }}>This model's results couldn't be shown. The problem has been reported.</p>
        <p style={{ marginBottom: 0 }}>
          <button type="button" className="link" onClick={() => window.location.reload()}>Reload the page</button>
          {" "}· <Link to="/models">All models</Link>
        </p>
      </div>
    </div>
  );
}
