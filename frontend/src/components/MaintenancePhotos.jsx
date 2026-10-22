import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createMaintenancePhotoLink,
  getMaintenanceOverview,
  getMaintenancePhotoBlob,
  linkMaintenancePhoto,
  listMaintenanceItems,
  listMaintenanceLocations,
  listMaintenanceWorkOrders,
  moveMaintenancePhoto,
  removeMaintenancePhoto,
  setMaintenanceCoordinates,
  unlinkMaintenancePhoto,
  uploadMaintenancePhoto,
} from "../api.js";
import {
  PLACE_KINDS, alsoOnText, placeKindWord, placeOptions, placePath, suggestions,
} from "../maintenancePhotoPlaces.js";
import Modal from "./Modal.jsx";
import { Field, FormModal, flatten, fmtDate } from "./MaintenanceParts.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";

// What the picker can choose from, loaded once per kind when it's first asked for.
const LOADERS = {
  Position: () => getMaintenanceOverview().then((d) => ({ positions: flatten(d.tree) })),
  Location: () => listMaintenanceLocations().then((d) => ({ locations: d.locations || [] })),
  Item: () => listMaintenanceItems().then((d) => ({ items: d.items || [] })),
  WorkOrder: () => listMaintenanceWorkOrders().then((d) => ({ workOrders: d.work_orders || [] })),
};

// "Link or move" a photo: show it on another position, location, item or work
// order too, or move it there (off this one). Suggestions first: what this page
// is related to (a work order's position and location, say).
function PhotoPlaceModal({ photo, here, hereLabel, related, onClose, onDone }) {
  const hints = suggestions(related, here.id, photo.also_on);
  const [mode, setMode] = useState("link");
  const [kind, setKind] = useState(hints[0]?.kind || "Position");
  const [to, setTo] = useState(hints[0]?.id || "");
  const [lists, setLists] = useState({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (lists[kind] !== undefined) return;
    let alive = true;
    setLoading(true);
    LOADERS[kind]()
      .then((d) => alive && setLists((l) => ({ ...l, [kind]: d })))
      .catch(() => alive && setLists((l) => ({ ...l, [kind]: {} })))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [kind, lists]);

  const options = placeOptions(kind, lists[kind]).filter((o) => o.id !== here.id);
  const word = placeKindWord(kind);
  const submit = async () => {
    onDone(mode === "move" ? await moveMaintenancePhoto(photo.id, to, here.id)
      : await linkMaintenancePhoto(photo.id, to));
  };
  return (
    <FormModal title="Link or move this photo" submitLabel={mode === "move" ? "Move" : "Link"} canSubmit={!!to}
               onClose={onClose} onSubmit={submit}>
      <div className="maint-place-modes" role="radiogroup" aria-label="Link or move">
        <label>
          <input type="radio" name="photo-place-mode" checked={mode === "link"} onChange={() => setMode("link")} />
          {" "}Also show it there <span className="lib-date">(it stays here too)</span>
        </label>
        <label>
          <input type="radio" name="photo-place-mode" checked={mode === "move"} onChange={() => setMode("move")} />
          {" "}Move it there <span className="lib-date">(off {hereLabel})</span>
        </label>
      </div>
      {hints.length > 0 && (
        <div>
          <span className="lib-date">Suggested</span>
          <div className="maint-place-hints">
            {hints.map((h) => (
              <button key={h.id} type="button" className={to === h.id ? "" : "secondary"}
                      onClick={() => { setKind(h.kind); setTo(h.id); }}>
                {h.name} <span className="maint-place-kind">· {placeKindWord(h.kind)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <Field label="Kind">
        <select value={kind} onChange={(e) => { setKind(e.target.value); setTo(""); }}>
          {PLACE_KINDS.map((k) => <option key={k} value={k}>{placeKindWord(k).replace(/^./, (c) => c.toUpperCase())}</option>)}
        </select>
      </Field>
      <Field label={word.replace(/^./, (c) => c.toUpperCase())}>
        <select value={to} onChange={(e) => setTo(e.target.value)} aria-label={`Which ${word}`}>
          <option value="">{loading ? "Loading…" : options.length ? "Choose…" : `No ${word}s yet`}</option>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </Field>
    </FormModal>
  );
}

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
// another phone, and the question when a photo carries a location. A photo
// can show in several places: each says where else it is, and "Link or move"
// puts it on another one. targetKind: Position, Location, Item or WorkOrder;
// related: places to suggest ({id, kind, name}).
export default function MaintenancePhotos({ title = "Photos", targetId, targetName, targetKind, photos, onChanged,
  related }) {
  const hereLabel = targetKind ? `this ${placeKindWord(targetKind)}` : "this page";
  const input = useRef(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [offer, setOffer] = useState(null); // {lat, lon}
  const [asked, setAsked] = useState(false);
  const [open, setOpen] = useState(null);
  const [link, setLink] = useState(null);
  const [placing, setPlacing] = useState(null);

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

  const confirm = useConfirm();
  const remove = async (p) => {
    if (!(await confirm({ title: "Remove this photo?", body: "It comes off everywhere it's shown. This can't be undone.", confirmLabel: "Remove photo" }))) return;
    await removeMaintenancePhoto(p.id).catch((e) => setError(e.message));
    setOpen(null);
    onChanged?.();
  };

  const unlink = async (p, place) => {
    if (!(await confirm({ title: "Take this photo off here?", body: `It comes off ${place.name || "this place"} but stays everywhere else it's shown.`, confirmLabel: "Take photo off" }))) return;
    try {
      await unlinkMaintenancePhoto(p.id, place.id);
      setOpen(place.id === targetId ? null : { ...p, also_on: p.also_on.filter((x) => x.id !== place.id) });
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
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
        <input ref={input} type="file" accept="image/*,.heic,.heif" multiple hidden
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
              <figcaption className="lib-date">
                {p.caption || fmtDate(p.taken_on || p.uploaded_on)}
                {p.also_on?.length > 0 && <span className="maint-photo-also">{alsoOnText(p.also_on)}</span>}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      <p className="lib-date">Photos are stored without their location or camera details.</p>

      {open && (
        <Modal title={open.caption || "Photo"} onClose={() => setOpen(null)}
               footer={<>
                 <button className="secondary" onClick={() => remove(open)}>Remove</button>
                 <button className="secondary" onClick={() => setPlacing(open)}>Link or move…</button>
                 <button onClick={() => setOpen(null)}>Close</button>
               </>}>
          <AuthImage photoId={open.id} size="full" className="maint-photo-full" alt={open.caption || "Photo"} />
          <p className="lib-date">
            {open.taken_on ? `Taken ${fmtDate(open.taken_on)} · ` : ""}added {fmtDate(open.uploaded_on)}
          </p>
          {open.also_on?.length > 0 && (
            <div className="maint-photo-places">
              <span className="lib-date">Shows on</span>
              <ul>
                <li>
                  <span>{hereLabel.replace(/^./, (c) => c.toUpperCase())}</span>
                  <button className="secondary maint-chip-small" onClick={() => unlink(open, { id: targetId, name: hereLabel })}>
                    Take off
                  </button>
                </li>
                {open.also_on.map((x) => (
                  <li key={x.id}>
                    {placePath(x) ? <Link to={placePath(x)} onClick={() => setOpen(null)}>{x.name}</Link> : x.name}
                    <span className="lib-date"> · {placeKindWord(x.kind)}</span>
                    <button className="secondary maint-chip-small" onClick={() => unlink(open, x)}>Take off</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Modal>
      )}
      {placing && (
        <PhotoPlaceModal photo={placing} here={{ id: targetId, name: targetName }} hereLabel={hereLabel} related={related}
                         onClose={() => setPlacing(null)}
                         onDone={() => { setPlacing(null); setOpen(null); onChanged?.(); }} />
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
