import { useSearchParams } from "react-router-dom";

// The open tab in the page's address (?tab=calc), so a link or a reload
// lands on it. The first tab has none: ``setTab(id, first)``.
export default function useTabParam() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab");
  const setTab = (id, first) => {
    const next = new URLSearchParams(params);
    if (!id || id === first) next.delete("tab");
    else next.set("tab", id);
    setParams(next, { replace: true });
  };
  return [tab, setTab];
}
