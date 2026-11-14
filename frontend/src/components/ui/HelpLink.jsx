import { BookIcon, PlayIcon } from "../icons.jsx";

// A page's help link (design system: Help link): a quiet small button that
// says what it does. "tour" starts a walkthrough on a sample (it takes over
// the screen); "guide" opens a how-to in the Help drawer (something to read).
// The label names which, so nobody is surprised.
//
//   kind      "tour" | "guide"
//   onClick   () => void
//   children  the label (default "Take the tour" / "Read the guide")
export const HELP_LABEL = { tour: "Take the tour", guide: "Read the guide" };

export default function HelpLink({ kind = "guide", onClick, children, className = "" }) {
  const Icon = kind === "tour" ? PlayIcon : BookIcon;
  return (
    <button type="button" className={"ghost sm help-link" + (className ? ` ${className}` : "")} onClick={onClick}>
      <Icon />
      {children || HELP_LABEL[kind] || HELP_LABEL.guide}
    </button>
  );
}
