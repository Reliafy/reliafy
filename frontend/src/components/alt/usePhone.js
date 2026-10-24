import { useEffect, useState } from "react";

// Whether the window is phone-width (the model frame's own breakpoint): the
// accelerated life page shows one life-stress chart and a switch there.
const PHONE = "(max-width: 720px)";

export default function usePhone() {
  const query = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(PHONE) : null);
  const [phone, setPhone] = useState(() => !!query()?.matches);
  useEffect(() => {
    const mq = query();
    if (!mq) return undefined;
    const on = () => setPhone(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return phone;
}
