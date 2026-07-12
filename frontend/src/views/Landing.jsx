import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import HeroPlot from "../components/HeroPlot.jsx";
import { useAuth } from "../AuthProvider.jsx";

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 12.5l5 5L20 6.5" />
  </svg>
);

// --- Per-feature mini illustrations -----------------------------------------
const VizModelling = () => (
  <svg viewBox="0 0 280 78" className="viz" aria-hidden="true">
    {[18, 36, 54].map((y) => <line key={y} x1="10" y1={y} x2="270" y2={y} className="viz-grid" />)}
    <path d="M14 64 L120 38 L270 14" className="viz-band" />
    <path d="M14 60 L120 34 L270 10" className="viz-line" />
    {[[24, 58], [60, 50], [96, 44], [132, 36], [168, 30], [204, 22], [240, 15]].map(([x, y], i) => (
      <circle key={i} cx={x} cy={y} r="3.2" className="viz-dot" />
    ))}
  </svg>
);
const VizRbd = () => (
  <svg viewBox="0 0 280 78" className="viz" aria-hidden="true">
    <path d="M44 39 H78 M126 39 C150 39 150 22 174 22 M126 39 C150 39 150 56 174 56 M214 22 C238 22 238 39 250 39 M214 56 C238 56 238 39 250 39" className="viz-edge" />
    <circle cx="30" cy="39" r="9" className="viz-node-io" />
    <rect x="80" y="29" width="46" height="20" rx="4" className="viz-node" />
    <rect x="176" y="12" width="38" height="20" rx="4" className="viz-node" />
    <rect x="176" y="46" width="38" height="20" rx="4" className="viz-node" />
    <circle cx="262" cy="39" r="9" className="viz-node-io" />
  </svg>
);
const VizStrategy = () => (
  <svg viewBox="0 0 280 78" className="viz" aria-hidden="true">
    <line x1="14" y1="68" x2="270" y2="68" className="viz-axis" />
    <path d="M20 22 C60 64 90 70 142 60 C200 50 235 40 262 18" className="viz-faint" />
    <path d="M20 64 C70 26 110 22 142 26 C190 32 235 56 262 70" className="viz-faint" />
    <path d="M20 30 C70 60 120 60 142 58 C200 52 240 40 262 24" className="viz-line" />
    <line x1="142" y1="20" x2="142" y2="68" className="viz-dash" />
    <circle cx="142" cy="58" r="4" className="viz-dot" />
  </svg>
);
const VizDatasets = () => (
  <svg viewBox="0 0 280 78" className="viz" aria-hidden="true">
    <rect x="20" y="12" width="240" height="54" rx="6" className="viz-grid-box" />
    <rect x="20" y="12" width="240" height="16" rx="6" className="viz-head" />
    <rect x="98" y="28" width="40" height="38" className="viz-col" />
    {[28, 41, 54].map((y) => <line key={y} x1="20" y1={y} x2="260" y2={y} className="viz-row" />)}
    {[60, 98, 138, 178, 218].map((x) => <line key={x} x1={x} y1="12" x2={x} y2="66" className="viz-row" />)}
  </svg>
);

const VizDegradation = () => (
  <svg viewBox="0 0 280 78" className="viz" aria-hidden="true">
    <line x1="14" y1="16" x2="270" y2="16" className="viz-dash" />
    <path d="M14 66 C80 58 150 44 262 20" className="viz-band" />
    <path d="M14 64 C80 56 150 42 262 18" className="viz-line" />
    {[[30, 62], [78, 56], [126, 48]].map(([x, y], i) => (
      <circle key={i} cx={x} cy={y} r="3.2" className="viz-dot" />
    ))}
    <line x1="238" y1="16" x2="238" y2="70" className="viz-dash" />
  </svg>
);
const VizRcm = () => (
  <svg viewBox="0 0 280 78" className="viz" aria-hidden="true">
    <path d="M24 16 V62 M24 26 H44 M24 44 H44 M24 62 H44" className="viz-edge" />
    <rect x="14" y="8" width="120" height="14" rx="4" className="viz-node" />
    {[20, 38, 56].map((y, i) => <rect key={y} x="48" y={y} width="96" height="12" rx="4" className="viz-row-box" />)}
    <rect x="170" y="20" width="66" height="12" rx="6" className="viz-ok" />
    <rect x="170" y="38" width="66" height="12" rx="6" className="viz-ok" />
    <rect x="170" y="56" width="66" height="12" rx="6" className="viz-bad" />
  </svg>
);

const FEATURES = [
  {
    viz: <VizModelling />,
    title: "Life-distribution modelling",
    body: "Fit Weibull, Lognormal, Exponential, Gamma, Normal, and proportional-hazards models to exact, censored, and truncated failure data. Probability plots with confidence bounds, goodness-of-fit, and a survival calculator.",
  },
  {
    viz: <VizRbd />,
    title: "Reliability block diagrams",
    body: "Wire components in series, parallel, k-of-n, and standby on a drag-and-drop canvas to compute system reliability, MTTF, importance measures, and minimal path/cut sets.",
  },
  {
    viz: <VizStrategy />,
    title: "Maintenance strategy",
    body: "Rank every candidate distribution against your data, compare two designs head-to-head, and find the cost-optimal preventive-replacement interval.",
  },
  {
    viz: <VizDegradation />,
    title: "Degradation & remaining useful life",
    body: "Fit per-unit wear paths to a failure threshold, then track in-service items and predict when each will cross it — with credible intervals that tighten as inspections come in.",
  },
  {
    viz: <VizRcm />,
    title: "Evidence-linked RCM",
    body: "Build Function → Failure → Mode worksheets where every maintenance decision cites the analysis that justifies it — and gets re-checked live when the data changes.",
  },
  {
    viz: <VizDatasets />,
    title: "Your data, organised",
    body: "Upload a CSV once and reuse it across models. Saved models reopen instantly, and everything is private to your account.",
  },
];

// Pricing copy. Keep the numbers in sync with backend/config.py
// (FREE_MAX_*, FREE_GRANT_CENTS, CREDIT_PACKS, PRO_MONTHLY_CREDIT_CENTS) and
// the live Stripe price.
const TIERS = (primaryHref) => [
  {
    name: "Open source",
    price: "Free",
    per: "self-hosted",
    blurb: "Run Reliafy on your own hardware. Your data never leaves it.",
    features: [
      "The full toolkit: modelling, RBDs, strategy, datasets",
      "Unlimited saves, single-user",
      "One-command install (docker compose)",
      "AGPL-3.0, source on GitHub",
    ],
    cta: { label: "View on GitHub", href: "https://github.com/Reliafy/reliafy", external: true, ghost: true },
  },
  {
    name: "Cloud Free",
    price: "$0",
    per: "forever",
    blurb: "The hosted app, ready in seconds. Everything you need to start.",
    features: [
      "3 saved datasets, 3 models, 1 RBD",
      "Degradation tracking: 1 model, 3 tracked assets",
      "1 RCM study with live evidence validation",
      "1 fleet failure forecast",
      "Join team workspaces free (view-only)",
      "Sample data and worked examples included",
      "25 AI credits to try the assistant",
      "Secure sign-in, private to your account",
    ],
    cta: { label: "Get started", href: primaryHref, ghost: true },
  },
  {
    name: "Pro",
    price: "US$19",
    per: "per month",
    blurb: "For working reliability engineers who live in their data.",
    featured: true,
    features: [
      "Unlimited datasets, models, and RBDs",
      "1,000 AI credits included every month",
      "Unlimited fleet monitoring (degradation & RUL)",
      "Unlimited evidence-linked RCM studies",
      "Fleet failure forecasting — spares demand from your models",
      "Team workspaces: create teams and edit together",
      "AI assistant: fits models and builds RBDs for you",
      "Top-up credit packs from $5 — credits never expire",
    ],
    cta: { label: "Start with Pro", href: primaryHref },
  },
];

export default function Landing() {
  const { user } = useAuth();
  const location = useLocation();
  const primaryHref = user ? "/modelling" : "/login?signup";
  const primaryLabel = user ? "Open the app" : "Get started";

  // Support /#pricing links from other pages: scroll once the section exists.
  useEffect(() => {
    if (location.hash) {
      document.querySelector(location.hash)?.scrollIntoView({ behavior: "smooth" });
    }
  }, [location.hash]);

  return (
    <div className="landing">
      <PublicNav />

      <section className="landing-hero">
        <div className="landing-hero-text">
          <div className="landing-eyebrow">Reliability engineering platform</div>
          <h1>From failure data to maintenance decisions.</h1>
          <p>
            Reliafy turns your reliability data into fitted life models, reliability
            block diagrams, and cost-optimal maintenance strategies — all in one
            place.
          </p>
          <div className="landing-cta">
            <Link className="cta cta-solid lg" to={primaryHref}>{primaryLabel}</Link>
          </div>
        </div>
        <div className="landing-hero-viz">
          <HeroPlot />
        </div>
      </section>

      <section className="landing-features" id="features">
        {FEATURES.map((f) => (
          <div className="landing-card" key={f.title}>
            <div className="landing-card-viz">{f.viz}</div>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </section>

      <section className="landing-spotlight">
        <div className="spotlight-text">
          <div className="landing-eyebrow">Reliability Centred Maintenance</div>
          <h2>Maintenance decisions that prove themselves.</h2>
          <p>
            Every decision in an RCM study links to the analysis behind it: a
            run-to-failure call cites the life model that shows failures are
            random, a fixed interval cites the cost-optimal replacement
            analysis, condition monitoring cites the degradation model.
          </p>
          <p>
            And the links stay live — when new data shows a "random" failure
            mode is actually wearing out, the study flags the decision as
            <strong> contradicted</strong> instead of letting it quietly go
            stale.
          </p>
        </div>
        <div className="spotlight-shot">
          <img src="/landing/rcm-worksheet.png" alt="An RCM worksheet with live evidence statuses, including a contradicted run-to-failure decision" loading="lazy" />
        </div>
      </section>

      <section className="landing-spotlight reverse">
        <div className="spotlight-text">
          <div className="landing-eyebrow">Degradation &amp; RUL</div>
          <h2>Know when it will fail — before it does.</h2>
          <p>
            Your inspection sheets already contain the failure dates of
            equipment that hasn't failed yet. Fit a degradation model from
            historical wear data, register the items you're running today, and
            get a remaining-useful-life estimate for each one.
          </p>
          <p>
            Every new reading tightens the prediction. Health badges turn from
            healthy to plan-replacement to replace-now while there's still
            time to act.
          </p>
        </div>
        <div className="spotlight-shot">
          <img src="/landing/rul-outlook.png" alt="A tracked item's remaining-useful-life outlook with a 95% credible band and predicted threshold crossing" loading="lazy" />
        </div>
      </section>

      <section className="landing-trio">
        <div className="trio-card">
          <h3>Work as a team</h3>
          <p>
            Shared team workspaces where everyone sees the same models,
            studies, and diagrams. Viewers are free; editing comes with Pro.
            Or share a single analysis, view-only, with anyone.
          </p>
        </div>
        <div className="trio-card">
          <h3>An assistant that does the work</h3>
          <p>
            Ask in plain language and the assistant acts in the app: fits
            models, builds RBDs, runs replacement calculations, tracks
            degradation, and drafts RCM studies — with your data, on your
            screen.
          </p>
        </div>
        <div className="trio-card">
          <h3>Open source at the core</h3>
          <p>
            The full toolkit is AGPL-licensed and self-hostable with one
            command. Your data can stay on your hardware; the cloud adds
            accounts, teams, and the assistant.
          </p>
        </div>
      </section>

      <section className="landing-pricing" id="pricing">
        <div className="landing-pricing-head">
          <div className="landing-eyebrow">Pricing</div>
          <h2>Free to run yourself. Effortless in the cloud.</h2>
          <p>The core is open source and always will be. The cloud adds accounts, the AI assistant, and zero setup.</p>
        </div>
        <div className="price-grid">
          {TIERS(primaryHref).map((t) => (
            <div key={t.name} className={"price-card" + (t.featured ? " featured" : "")}>
              {t.featured && <span className="price-flag">Most popular</span>}
              <h3>{t.name}</h3>
              <div className="price-amount">
                {t.price}
                <span className="price-per">{t.per}</span>
              </div>
              <p className="price-blurb">{t.blurb}</p>
              <ul className="price-list">
                {t.features.map((f) => (
                  <li key={f}><CheckIcon />{f}</li>
                ))}
              </ul>
              {t.cta.external ? (
                <a className={"cta lg " + (t.cta.ghost ? "cta-ghost" : "cta-solid")} href={t.cta.href} target="_blank" rel="noreferrer">
                  {t.cta.label}
                </a>
              ) : (
                <Link className={"cta lg " + (t.cta.ghost ? "cta-ghost" : "cta-solid")} to={t.cta.href}>
                  {t.cta.label}
                </Link>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="landing-band">
        <h2>Built for reliability engineers.</h2>
        <p>Upload a CSV, fit a model, build a system, and decide when to act — in one place.</p>
        <Link className="cta cta-solid lg" to={primaryHref}>{primaryLabel}</Link>
      </section>

      <PublicFooter />
    </div>
  );
}
