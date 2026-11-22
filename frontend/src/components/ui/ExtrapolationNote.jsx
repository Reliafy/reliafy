// The one warning that an answer lies outside the data behind it (the words
// come from extrapolation.js). A caveat box: amber, with "!" so the tone
// isn't colour alone. Renders nothing without words.
export default function ExtrapolationNote({ words, className = "" }) {
  if (!words) return null;
  return (
    <p className={`calc-warn extrapolation-note${className ? ` ${className}` : ""}`} role="note">
      <span aria-hidden="true">! </span>
      <span className="sr-only">Extrapolation: </span>
      {words}
    </p>
  );
}
