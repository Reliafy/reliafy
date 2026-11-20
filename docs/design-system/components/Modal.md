# Modal

A dialog over the page, for a short, self-contained step (a confirmation, a small form, a picker). Work that needs the page beside it opens in a table pane instead (the first UI principle); a modal is the exception.

## Behaviour (every modal, no opt-in)

- **Focus moves in** when it opens: to the dialog itself, or to the field inside that took it (`autoFocus`).
- **Focus stays in.** Tab and Shift+Tab go round the dialog's own controls and never reach the page behind it. A dropdown inside that uses the Tab itself (picking its highlighted option) keeps it.
- **Focus goes back** to whatever had it (the button that opened it) when the dialog closes, however it closes: Escape, ×, a click on the overlay, or one of its own buttons. A dialog that navigated to another page leaves that page's focus alone.
- **Escape closes only the topmost** dialog when one opens another; a dropdown that takes the Escape to close its list keeps the dialog open.
- `locked` (a request in flight): Escape, × and the overlay don't close it.

The help drawer follows the same focus rules (`useDialogFocus` and `trapTab` in `components/focusTrap.js`). The confirm dialog and the phone menu drawer have their own equivalent code.

## Props

`title` (the heading, which names the dialog for screen readers), `onClose`, `locked`, `footer` (its buttons, primary last), `className`, `overlayClassName` (e.g. a dialog that becomes a sheet on a phone), children.

## Look

`radius-lg`, `shadow-lg`, over the `scrim`. The close button is the × at the top right.

Source: `frontend/src/components/Modal.jsx`.
