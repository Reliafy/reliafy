// The app's buttons (#310). A bare <button> is the primary style; the other
// variants are classes on it, so plain markup and this component look alike:
//   primary    the one next-step action in a view (blue fill)
//   secondary  every other action (white, outlined)
//   ghost      low-emphasis actions in toolbars and rows (no outline)
//   danger     destructive actions (red text and outline)
//   link       an inline text link that runs an action
// size="sm" is the compact size used in toolbars, rows and cards.
const VARIANTS = new Set(["primary", "secondary", "ghost", "danger", "link"]);

export function buttonClass(variant = "primary", size, className) {
  const v = VARIANTS.has(variant) ? variant : "primary";
  return [v === "primary" ? "" : v === "danger" ? "secondary danger" : v, size === "sm" ? "sm" : "", className || ""]
    .filter(Boolean)
    .join(" ");
}

export default function Button({ variant = "primary", size, className, type = "button", ...rest }) {
  return <button type={type} className={buttonClass(variant, size, className) || undefined} {...rest} />;
}
