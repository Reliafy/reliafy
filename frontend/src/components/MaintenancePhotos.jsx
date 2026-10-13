import { useEffect, useRef, useState } from "react";
import {
  createMaintenancePhotoLink,
  getMaintenancePhotoBlob,
  removeMaintenancePhoto,
  setMaintenanceCoordinates,
  uploadMaintenancePhoto,
} from "../api.js";
import Modal from "./Modal.jsx";
import { fmtDate } from "./MaintenanceParts.jsx";

// A photo from the authenticated endpoint, shown through an object URL.
function AuthImage({ photoId, size = "thumb", alt, className, onClick }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url = null;
    let alive = true;
    getMaintenancePhotoBlob(photoId, size)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        if (alive) setSrc(url);
      })
      .catch(() => {});
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [photoId, size]);
  return src ? <img src={src} alt={alt} className={className} onClick={onClick} />
    : <div className={`${className || ""} maint-photo-blank`} />;
}

// Photos of one node (a position, its fitted item, a work order): a gallery,
// "Add photos" (several at once; the phone's camera on a phone), a link for
// another phone, and the question when a photo carries a location.
export default function MaintenancePhotos({ title = "Photos", targetId, targetName, photos, onChanged }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [offer, setOffer] = useState(null); // {lat, lon}
  const [asked, setAsked] = useState(false);
  const [open, setOpen] = useState(null);
  const [link, setLink] = useState(null);

  const onFiles = async (files) => {
    setError(null);
    let first = null;
    let n = 0;
    for (const file of files) {
      n += 1;
      setBusy(`Uploading ${n} of ${files.length}…`);
      try {
        const r = await uploadMaintenancePhoto(targetId, file);
        if (r.location_offer && !first) first = r.location_offer;
      } catch (e) {
        setError(`${file.name}: ${e.message}`);
      }
    }
    setBusy(null);
    if (first && !asked) setOffer(first);
    onChanged?.();
  };

  const answer = async (save) => {
    setAsked(true);
    const o = offer;
    setOffer(null);
    if (save) {
      try {
        await setMaintenanceCoordinates(targetId, o.lat, o.lon, "photo");
        onChanged?.();
      } catch (e) {
        setError(e.message);
      }
    }
  };

  const remove = async (p) => {
    if (!window.confirm("Remove this photo?")) return;
    await removeMaintenancePhoto(p.id).catch((e) => setError(e.message));
    setOpen(null);
    onChanged?.();
  };

  const phoneLink = async () => {
    try {
      setLink(await createMaintenancePhotoLink(targetId));
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <section className="card">
      <div className="maint-head">
        <h2>{title}</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          <button className="secondary" onClick={phoneLink}>Link for a phone</button>
          <button onClick={() => input.current?.click()} disabled={!!busy}>{busy || "Add photos"}</button>
        </div>
        <input ref={input} type="file" accept="image/*" multiple hidden
               onChange={(e) => { onFiles([...e.target.files]); e.target.value = ""; }} />
      </div>
      {error && <div className="card error">{error}</div>}
      {offer && (
        <div className="maint-ask">
          <p>
            A photo has a location ({offer.lat.toFixed(5)}, {offer.lon.toFixed(5)}). Save it as where{" "}
            {targetName || "this equipment"} is?
          </p>
          <div className="maint-row" style={{ marginTop: 0 }}>
            <button onClick={() => answer(true)}>Save location</button>
            <button className="secondary" onClick={() => answer(false)}>No thanks</button>
          </div>
        </div>
      )}
      {photos.length === 0 ? (
        <p className="lib-date">No photos yet. Nameplates are the most useful: make, model and serial.</p>
      ) : (
        <div className="maint-photos">
          {photos.map((p) => (
            <figure key={p.id}>
              <AuthImage photoId={p.id} className="maint-photo" alt={p.caption || "Photo"} onClick={() => setOpen(p)} />
              <figcaption className="lib-date">{p.caption || fmtDate(p.taken_on || p.uploaded_on)}</figcaption>
            </figure>
          ))}
        </div>
      )}
      <p className="lib-date">Photos are stored without their location or camera details.</p>

      {open && (
        <Modal title={open.caption || "Photo"} onClose={() => setOpen(null)}
               footer={<>
                 <button className="secondary" onClick={() => remove(open)}>Remove</button>
                 <button onClick={() => setOpen(null)}>Close</button>
               </>}>
          <AuthImage photoId={open.id} size="full" className="maint-photo-full" alt={open.caption || "Photo"} />
          <p className="lib-date">
            {open.taken_on ? `Taken ${fmtDate(open.taken_on)} · ` : ""}added {fmtDate(open.uploaded_on)}
          </p>
        </Modal>
      )}
      {link && (
        <Modal title="Add photos from a phone" onClose={() => setLink(null)}
               footer={<button onClick={() => setLink(null)}>Done</button>}>
          <p>Open this link on the phone (no sign-in needed). It takes up to {link.max_photos} photos and
            expires in 30 minutes.</p>
          <p><input readOnly value={link.url} style={{ width: "100%" }} onFocus={(e) => e.target.select()} /></p>
        </Modal>
      )}
    </section>
  );
}
