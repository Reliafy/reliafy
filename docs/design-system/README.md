# Reliafy design system

Reliafy is reliability engineering software for asset-intensive organisations: it turns failure and condition data into decisions — when to replace, when to inspect, how many spares to hold. The interface is an instrument: a warm paper ground, one cobalt accent, hairline borders, and numbers set to be read.

This is version 2: the app's look, with every value following a few rules.

## Where it lives

- **`tokens.json` (this folder) is the source** of every colour, type size, space, radius, shadow and control height, for both themes. Change values here, never in CSS.
- **`frontend/src/tokens.css` is generated from it**: run `npm run tokens` in `frontend/`. `tokensSync.test.js` fails if the two differ, and `tokenNames.test.js` fails on a name from before v2.
- **`components/`** holds one guideline per shared component (`frontend/src/components/ui/` and `RowMenu`). Update the guideline in the same change as the component.
- **The logo and icons** are the app's own: `frontend/public/favicon.svg`, `frontend/src/components/Logo.jsx`, `frontend/src/components/icons.jsx`.
- **The Reliafy design system artifact** on claude.ai is the browsable copy of this folder, for reading and sharing. It is refreshed from here after a change merges; edits made there don't reach the app.

## The rules in one place

- **Two themes, one set of names.** Light and dark use the same token names; only the values behind them change.
- **Colour comes in ramps.** Eight colours, each in eleven steps from 50 (lightest) to 950 (darkest). A step number means the same lightness in every colour, so a step does the same job everywhere (below).
- **Components use roles, not ramps.** Build with `text`, `bg-surface`, `accent`, `danger-text`, … These semantic tokens point at ramp steps. Reach for a raw step (`teal-200`) only for something no role covers.
- **Eight type sizes, each with its own line height** on a 4px grid: 12/16, 13/20, 14/20, 16/24, 20/28, 24/32, 32/40, 40/48. Always use `fs-N` with `lh-N`, or a named style.
- **Three weights:** 400 for reading, 500 for labels, 600 for headings and emphasis. Never 700.
- **Everything sits on a 4px grid:** spacing, line heights and control heights.
- **One control height per size:** buttons, inputs, selects and segmented controls are all 32px (`control-md`), or 28px compact (`control-sm`), or 40px on a phone (`control-lg`).

## Colour

### How the ramps work

Every colour has the same steps, and each step does one job:

| Step | Job | Contrast it guarantees |
| --- | --- | --- |
| 50 | Page canvas (neutral); the background of a status or kind box | — |
| 100 | Hover and selected tints; subtle fills; quiet dividers | — |
| 200 | Borders of tinted boxes; standard dividers | — |
| 300 | Decorative strokes, chart axes | — |
| 400 | Disabled text and icons only | ≈2.3:1, never readable text |
| 500 | Control borders, icons, chart marks | ≥3:1 on white and canvas |
| **600** | **First step safe for text.** Solid fills with white text; icons | ≥4.5:1 on 0, 50, 100 and its own 50 |
| 700 | Coloured text on its own tint; hover of a 600 fill; secondary text | ≥5.5:1 on its own 100 |
| 800–950 | Strong text, headings on tints; 950 is the main text colour | — |

So the colour of a thing is a role plus a step. For example, a teal kind is a `teal-50` box with a `teal-200` border and `teal-600` dot. A warning is an `amber-50` box with a `amber-200` border, an `amber-600` icon and `amber-700` text.

### The colours

- **Neutral** is a warm grey, tinted towards the paper canvas, so text, lines and backgrounds all belong together. (Before, the text was a cool blue-black on warm paper.)
- **Blue** is the brand and the only accent.
- **Green, amber, red** mean something: good, a caveat, bad. Nothing else.
- **Teal, violet, pink** are for telling kinds apart: model kinds, RBD blocks, fault-tree gates, maintenance types. They never mean good or bad. Pink replaces the old amber kind, which looked like a warning. Grey (`cat-grey`) is the "other" kind.

### Roles

- **Grounds:** `bg-canvas` for the page; `bg-surface` (white) for cards, controls, menus; `bg-subtle` for recessed fills such as table headers, wells and addons.
- **Lines:** `border` for cards and tables, `border-subtle` for inner dividers. Use `border-control` for anything you type into or press. It meets 3:1, so the box is visible; hover makes it `border-control-hover`.
- **Text:** `text` for content, `text-secondary` for labels and meta lines, `text-tertiary` for hints and placeholders. `text-disabled` is for disabled items only. `text-on-fill` goes on any solid 600 fill.
- **Accent:** `accent` is the fill of the one primary button, the switch "on" state and selection markers. `accent-hover` is its hover/pressed fill and `accent-text` is for links and accent words. A chosen chip or segment gets `accent-subtle` with an `accent-border`, and hovered rows get `accent-wash`. Never use the accent for decoration.
- **Status:** each of `success`, `warning` and `danger` has four tokens: the colour itself (icons, fills), `-text`, `-bg` and `-border`. Always pair a status colour with a word or a ✓ ! ✕, because green and red differ by hue more than lightness.
- **Kinds:** each of `cat-teal`, `cat-violet` and `cat-pink` has a `-bg` and a `-border`; `cat-grey` has neither. Text on a kind tint stays `text`.
- **Other:** `icon-standard` is the RCM performance-standard icon. `scrim` dims the page behind modals and `scroll-shade` marks a table edge with more to scroll to. `brand-mark` (#2f6df6) is the logo square only, and never changes with the palette.

### Dark theme

There are two themes, `light` and `dark`, built from the same ramps. Only the roles change, so a component written with roles works in both without changes.

- **Grounds go darker as they recede.** `bg-canvas` is `neutral-975`, `bg-surface` (cards) `neutral-950` and `bg-subtle` `neutral-925`. A card is lighter than the page, the reverse of light mode, which is how depth reads on dark.
- **Text flips to the light end.** `text` is `neutral-50`, `text-secondary` is `neutral-300` and `text-tertiary` is `neutral-400`. All of them are 7:1 or better.
- **Coloured text uses the 400 step** instead of 700 (`accent-text`, `success-text`, …). That step is 6.6:1 or better on every dark ground.
- **Solid fills stay at 600** (`accent`, `success`, `warning`, `danger`), so white text on them keeps 5:1 or better in both themes.
- **Tints are quiet.** Status, kind and accent backgrounds are their colour at about 16% over the surface, and borders are at about 45%. A full-strength dark red box shouts.
- **Shadows get heavier** (black at 40–60%), because a soft grey shadow disappears on a dark ground. The focus ring becomes `blue-400` with a gap in the surface colour.
- **Charts:** `chart-1` becomes `blue-400` and `chart-7` becomes `violet-400` (the indigo is 2:1 on dark). Gridlines and axes move to the dark neutrals.
- **Known gap:** the `danger` fill is 2.95:1 against the dark surface, just under 3:1. The ✕ and the word carry the meaning.

Turn it on with `data-theme="dark"` on `<html>`. To follow the system setting, set the attribute from `prefers-color-scheme` and let a toggle override it. Set `color-scheme: dark` too, so native selects and scrollbars match.

### Focus

Every control shows `focus-ring` on keyboard focus: a 2px gap in the surface colour, then a solid 2px accent ring (`blue-600` in light, `blue-400` in dark; 5:1 or better on any surface). Inside a joined group or a table cell, use `focus-ring-inset`. Never remove focus without replacing it.

## Charts

Series carry a role, not a colour of their own:

- The fitted curve is `chart-1` (the accent) and its confidence band is `chart-band`.
- Observed data is `chart-data-ink`; a band around it is `chart-band-neutral`.
- Reference lines are dashed `chart-reference`. An optimum is a `text` marker with a label.
- Several comparable series take `chart-1` … `chart-8` **in order, never by rank**. Series 2–8 are unchanged from the app: they were checked for colour-vision deficiency on adjacent pairs.
- Use a transparent background with `chart-grid` on the y-axis only. Axis lines and ticks are `chart-axis`, axis titles use the `small` style in `text-secondary`, and the legend sits top-left above the plot. Bars get `radius-sm` corners.
- Write numbers in full ("12,000") and dates day first ("1 Nov 2026").

## Type

IBM Plex Sans for everything; IBM Plex Mono for IDs, code and dense numeric readouts. Both load from Google Fonts.

| Style | Size / line | Weight | Use |
| --- | --- | --- | --- |
| `display-lg` | 40/48, -0.02em | 600 | Landing hero only |
| `display` | 32/40, -0.02em | 600 | Public-page article and section titles |
| `heading-lg` | 24/32, -0.01em | 600 | Page titles; article h2 |
| `heading` | 20/28, -0.01em | 600 | Section headings; stat values |
| `heading-sm` | 16/24 | 600 | Card titles |
| `heading-xs` | 14/20 | 600 | Section titles inside a card or form |
| `body-lg` | 16/24 | 400 | The answer sentence; ledes |
| `body` | 14/20 | 400 | Default text, controls |
| `body-strong` | 14/20 | 600 | Buttons, emphasised values |
| `small` | 13/20 | 400 | Subtitles, meta lines, dense table cells |
| `label` | 13/20 | 500 | Field labels, breadcrumbs, small buttons |
| `caption` | 12/16 | 500 | Chips, table headers, counts |
| `help` | 12/16 | 400 | Field help, footnotes |
| `mono` | 13/20 | 400 | IDs, code, numeric readouts |

- Only the 32px and larger display sizes are for public pages. The app tops out at `heading-lg`.
- Numbers that are compared (stats, tables, result sentences) use tabular numerals.
- Controls use 16px text on a phone so iOS doesn't zoom.

## Space, shape, depth

- **Spacing:** `space-N` is N × 4px: 4, 8, 12, 16, 20, 24, 32, 48, 64.
  - Inside a control: `space-3` horizontal.
  - Between related things: `space-2`.
  - Between fields: `space-3`.
  - Between sections: `space-4`.
  - Card padding and the gap between cards: `space-6`.
  - Between page regions: `space-8`.
- **Radius:** `radius-md` (6px) for controls, buttons, chips and menus. `radius-lg` (12px) for cards, modals, drawers and result boxes. `radius-sm` (4px) for small marks and chart bars. `radius-full` for switches, avatars, discs and pills.
- **Borders, not shadows.** Cards get a 1px `border` plus `shadow-sm` as a hairline lift. `shadow-md` is for sticky bars and dragged items; `shadow-lg` is for menus, popovers, modals and drawers.
- **Icons:** `icon-sm` 14, `icon-md` 16, `icon-lg` 20.
- **Motion:** 150ms on colour, border and shadow. Nothing bounces.

## Content fundamentals

Write like an engineer briefing a manager: **the answer first, then the detail.**

- Use plain words and short sentences, with no jargon the user didn't bring. Say what a thing does, not how clever it is.
- Lead results with the decision, numbers in bold: "Replace at **9,800 hours** to cut the cost per hour by **31%**." Not "Optimal replacement interval: 9,800".
- Use sentence case everywhere: buttons, tabs, headings, chips.
- Address the user as "you". Use British/Australian spelling: organisation, colour.
- Always show the unit ("14,210 h", "Weibull · hours"). Write numbers in full ("12,000", never "12k") and dates day first ("12 Nov 2026").
- Errors say what to do: "Enter a time above 0."
- Distribution parameters use SurPyval names (Weibull `alpha`, `beta`).
- No emoji. Glyphs carry meaning: ✓ good, ! caveat, ✕ bad, ⋯ more, › disclosure, · separator.

## Layout

- The app has a sticky top bar on `bg-surface` with a `border` bottom edge, and a collapsible sidebar. Content sits on `bg-canvas`.
- A page is a `PageHeader` (breadcrumb, name, one meta line, one primary action), then cards.
- A result page is a `ResultSummary` (a sentence plus at most four stat tiles), then one chart, then the details folded away.
- Nothing scrolls the page sideways at 400px wide: wide tables scroll inside their own container.

## Components

`components/` holds the shared primitives: `Button`, `Card`, `Chip`, `ChoiceChips`, `ContextMenu`, `Field`, `HelpLink`, `InputGroup`, `SegmentedControl`, `Switch`, `Tabs`, `PageHeader`, `Section` and `ResultSummary`. Their guidelines are in `components/`; the design system artifact shows a preview of each.

- Use one primary button per view; everything else is secondary or ghost. Destructive actions are `danger` text and outline, never a red fill.
- Don't nest grey panels in a card; divide it with `Section`s.
- A thing's own actions go in a `ContextMenu` on right-click, and also behind its ⋯ button, never only on right-click.
- A page's help is one `HelpLink` after its purpose: "Take the tour" or "Read the guide", never "Show me how".
- Pick a saved value from a few with `ChoiceChips`. Switch a view with `SegmentedControl`, move between panels with `Tabs` (more panels than fit: `Tabs` with `overflow`, the rest under "⋯ N"), and apply a setting at once with `Switch`.

## Iconography

Use the app's own icon set in `assets/Icons/`: a 24px grid, 1.7px hairline strokes, round caps and joins, drawn in `currentColor`. The logo is in `assets/Logos/`; set the name beside it in the `heading` style.
