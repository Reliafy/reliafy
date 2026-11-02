import { useEffect, useState } from "react";
import { getBilling } from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { showProTags } from "../plan.js";

// The plan, fetched once per page load and shared by every tag.
let billingPromise = null;
const loadBilling = () => {
  if (!billingPromise) billingPromise = getBilling().catch(() => null);
  return billingPromise;
};

// Whether this user should see "Pro" on Pro-only actions (plan.js has the rule).
export function useProTags() {
  const config = useAppConfig();
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!config.billing) return undefined;
    let alive = true;
    loadBilling().then((b) => { if (alive) setShow(showProTags(b)); });
    return () => { alive = false; };
  }, [config.billing]);
  return show;
}

// A small "Pro" tag beside a Pro-only action, shown to users without Pro
// before they click (the 402 card still explains after). ``always``: the
// caller already knows the user isn't entitled (e.g. the server said so).
export default function ProTag({ always = false }) {
  const show = useProTags();
  if (!show && !always) return null;
  return <span className="pro-tag" title="Part of Pro">Pro</span>;
}
