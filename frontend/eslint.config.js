// The design system's rules that live in the markup (docs/design-system).
// Only these: it isn't a general style check. `npm run lint:js`.
const SELECT = "No raw <select>: use the shared Select (components/Select.jsx, or Select from components/ui/Controls.jsx in a form). See docs/design-system/components/Select.md.";

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    // Inline comments are ignored: the code's react-hooks comments name a plugin this
    // config doesn't load, and a raw <select> can't be waved through one at a time.
    linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: "off" },
    rules: {
      "no-restricted-syntax": ["error", { selector: "JSXOpeningElement[name.name='select']", message: SELECT }],
    },
  },
  {
    // The shared Select itself draws no <select>; these files only name it in comments.
    files: ["src/components/Select.jsx", "src/components/ui/Controls.jsx"],
    rules: { "no-restricted-syntax": "off" },
  },
];
