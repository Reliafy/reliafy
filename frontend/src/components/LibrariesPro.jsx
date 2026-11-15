import { Link } from "react-router-dom";
import Modal from "./Modal.jsx";
import { useProTags } from "./ProTag.jsx";

// Libraries and the plans (Derryn, 15 Nov 2026): public libraries are free to browse and copy from;
// making a library, adding to it, editing, sharing and publishing it are Pro. The server is the
// source of truth (402 ``pro_required``, billing.libraries_allowed); this is what users without
// Pro see before they click.

export const LIBRARIES_PRO_TITLE = "Make and share your own libraries with Pro";
export const LIBRARIES_PRO_TEXT =
  "Public libraries are free to browse and copy from. Pro adds libraries of your own: keep copies of your "
  + "datasets and models together, share them with other workspaces, and publish them with a licence and citation.";

// Whether this user can't make or change libraries (Free, or the retired Agent plan, with billing on).
// False while the plan loads, for Pro, operators and self-hosted installs.
export function useLibrariesLocked() {
  return useProTags();
}

// The upgrade note in a page (a library its owner kept from Pro, the empty "Yours" section).
export function LibrariesProNotice({ children = null }) {
  return (
    <div className="card upgrade-nudge" role="status">
      <p><strong>{LIBRARIES_PRO_TITLE}.</strong> {children || LIBRARIES_PRO_TEXT}{" "}
        <Link to="/billing">See what Pro adds</Link>
      </p>
    </div>
  );
}

// The upgrade prompt that New library…, Add to library… and Upload into a library open without Pro.
export function LibrariesProDialog({ onClose }) {
  return (
    <Modal title={LIBRARIES_PRO_TITLE} onClose={onClose} trapFocus
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose}>Not now</button>
               <Link className="cta cta-solid" to="/billing" onClick={onClose}>See what Pro adds</Link>
             </>
           )}>
      <p className="rw-fhelp">{LIBRARIES_PRO_TEXT}</p>
      <p className="rw-fhelp">Datasets and models you’ve already copied from a library stay yours on every plan.</p>
    </Modal>
  );
}
