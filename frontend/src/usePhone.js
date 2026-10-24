import { useEffect, useState } from "react";

// True while the window is phone-width (720 px and under), following it as
// it changes. Pages that lay out differently on a phone (the asset Explorer,
// the RCM worksheet) share it.
export const PHONE_QUERY = "(max-width: 720px)";

export default function usePhone() {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const onChange = () => setPhone(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return phone;
}
