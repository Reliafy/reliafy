import { Link } from "react-router-dom";
import HeroPlot from "./components/HeroPlot.jsx";

// SEO product pages (buyer-intent keywords). One primary keyword per page —
// never two pages chasing the same term. Each is prerendered to static HTML
// with SoftwareApplication JSON-LD; content pages under /learn link up here.

const softwareJsonLd = (name, description, path) => ({
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name,
  description,
  url: `https://reliafy.com${path}`,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web browser",
  offers: [
    { "@type": "Offer", price: "0", priceCurrency: "USD", description: "Cloud Free plan" },
    { "@type": "Offer", price: "19", priceCurrency: "USD", description: "Pro plan, per month" },
  ],
  license: "https://www.gnu.org/licenses/agpl-3.0.html",
  publisher: { "@type": "Organization", name: "Reliafy", url: "https://reliafy.com" },
});

// Larger RBD illustration for the RBD page hero.
const RbdHero = () => (
  <svg className="hero-plot" viewBox="0 0 520 340" role="img" aria-label="Reliability block diagram with series, parallel, and 2-of-3 structures">
    <text x="46" y="26" className="hp-title">RELIABILITY BLOCK DIAGRAM</text>
    <path d="M60 170 H120 M200 170 H236 M236 170 C268 170 268 100 300 100 M236 170 C268 170 268 170 300 170 M236 170 C268 170 268 240 300 240 M380 100 C412 100 412 170 444 170 M380 170 H444 M380 240 C412 240 412 170 444 170" className="viz-edge" style={{ strokeWidth: 2 }} />
    <circle cx="48" cy="170" r="12" className="viz-node-io" />
    <rect x="122" y="152" width="78" height="36" rx="6" className="viz-node" />
    <text x="161" y="174" textAnchor="middle" className="hp-tick">Pump</text>
    <rect x="300" y="82" width="80" height="36" rx="6" className="viz-node" />
    <text x="340" y="104" textAnchor="middle" className="hp-tick">Valve A</text>
    <rect x="300" y="152" width="80" height="36" rx="6" className="viz-node" />
    <text x="340" y="174" textAnchor="middle" className="hp-tick">Valve B</text>
    <rect x="300" y="222" width="80" height="36" rx="6" className="viz-node" />
    <text x="340" y="244" textAnchor="middle" className="hp-tick">Valve C</text>
    <text x="340" y="290" textAnchor="middle" className="hp-tick">2-of-3 redundancy</text>
    <circle cx="458" cy="170" r="12" className="viz-node-io" />
  </svg>
);

export const PRODUCT_PAGES = [
  {
    path: "/weibull-analysis-software",
    title: "Weibull Analysis Software — Online, Free to Start | Reliafy",
    description:
      "Weibull analysis in your browser: fit life distributions to censored and suspended data, get confidence bounds and B10 life, straight from a CSV. Free to start, open source.",
    eyebrow: "Weibull analysis",
    h1: "Weibull analysis software that runs in your browser",
    lede:
      "Upload failure data — including suspensions — and get a fitted Weibull with probability plot, confidence bounds, and B-lives in seconds. No install, no licence server, free to start.",
    hero: <HeroPlot />,
    jsonld: (p) => softwareJsonLd("Reliafy — Weibull analysis", p.description, p.path),
    body: (
      <>
        <h2>Censored and suspended data, handled properly</h2>
        <p>
          Most real maintenance datasets are dominated by items that <em>haven't</em> failed:
          preventive replacements, items still in service, units retired for other reasons.
          Ignore those suspensions and every life estimate comes out biased low. Reliafy fits by
          maximum likelihood with full support for right-censored, left-censored, interval-censored,
          and truncated observations — so the units that survived count as the evidence they are.
          (If you've been doing <Link to="/learn/weibull-analysis-in-excel">Weibull analysis in Excel</Link>,
          this is the part Excel can't do.)
        </p>

        <h2>More than Weibull</h2>
        <p>
          Fit Weibull, Lognormal, Exponential, Gamma, and Normal distributions to the same data —
          or <Link to="/learn/b10-life">rank them side by side</Link> by AIC with one click and let
          the data pick. Proportional-hazards models handle covariates when operating conditions
          differ across the fleet. Every fit reports its parameters, goodness of fit, B10 life, and
          a probability plot you can read at a glance.
        </p>

        <h2>Confidence bounds you can defend</h2>
        <p>
          Point estimates aren't decisions. Every fitted model carries confidence bounds on the
          probability plot and through the survival calculator, so "the B10 life is 4,100 hours"
          comes with the uncertainty attached — which is what your maintenance interval actually
          hinges on.
        </p>

        <h2>From maintenance records to fitted model</h2>
        <p>
          Import a CSV exported from your CMMS or a plain spreadsheet: map the time column, mark
          which events are failures and which are suspensions, and fit. Datasets are saved and
          reusable, so next quarter's update is an append, not a rebuild. Fitted models flow
          straight into the rest of the platform — optimal replacement intervals, reliability block
          diagrams, and evidence-linked RCM studies.
        </p>

        <h2>Free to start, open source at the core</h2>
        <p>
          The cloud free tier includes saved datasets and models with sample data to learn on. The
          full engine is AGPL-licensed and self-hostable with one command if your data can't leave
          site. Statistical core built on the open-source <code>surpyval</code> library.
        </p>

        <h2>Keep reading</h2>
        <ul>
          <li><Link to="/learn/weibull-analysis">Weibull analysis: a complete, practical guide</Link></li>
          <li><Link to="/learn/weibull-analysis-in-excel">How to do Weibull analysis in Excel — and where it breaks</Link></li>
          <li><Link to="/learn/censored-data-suspensions">Censored data and suspensions: why your MTBF is probably wrong</Link></li>
          <li><Link to="/learn/b10-life">B10 life: definition and a worked example</Link></li>
        </ul>
      </>
    ),
    band: {
      h2: "Fit your first Weibull in the next five minutes.",
      p: "Upload a CSV, mark the suspensions, and read the plot — free.",
    },
  },
  {
    path: "/rcm-software",
    title: "RCM Software — Link Maintenance Decisions to Failure Evidence | Reliafy",
    description:
      "RCM software where every maintenance decision cites the life model, replacement analysis, or degradation model behind it — and gets flagged when new data contradicts it.",
    eyebrow: "Reliability centred maintenance",
    h1: "Reliability centred maintenance, backed by your failure data",
    lede:
      "Build Function → Failure → Mode worksheets where every decision links to the analysis that justifies it — and stays linked, so the study flags itself when the data stops agreeing.",
    hero: (
      <img
        src="/landing/rcm-worksheet.png"
        alt="An RCM worksheet with live evidence statuses, including a contradicted run-to-failure decision"
        style={{ width: "100%", borderRadius: 10 }}
      />
    ),
    jsonld: (p) => softwareJsonLd("Reliafy — RCM software", p.description, p.path),
    body: (
      <>
        <h2>Decisions that cite their evidence</h2>
        <p>
          Most RCM tools are structured note-taking: the worksheet records that the team chose a
          fixed 6-month interval, but not <em>why</em>, and nothing ever checks the why again. In
          Reliafy, each decision links to the analysis behind it — a run-to-failure call cites the
          fitted life model showing failures are random; a fixed interval cites the cost-optimal
          replacement analysis; an on-condition task cites the degradation model; a failure-finding
          interval cites the availability calculation.
        </p>

        <h2>Contradicted, not quietly stale</h2>
        <p>
          The links stay live. When new failure data shows a "random" failure mode is actually
          wearing out, the study flags that decision as <strong>contradicted</strong> — with the
          evidence one click away — instead of letting the worksheet drift out of date for five
          years. Each study rolls up how many decisions are supported, unverified, or contradicted,
          so an audit starts from a dashboard rather than a binder.
        </p>

        <h2>The classic structure, without the ceremony</h2>
        <p>
          Worksheets follow the standard decomposition — functions, functional failures, failure
          modes with effects and consequences, then the maintenance decision. Mode-level fields
          keep the analysis honest (what does failure look like, how is it detected), and the
          whole worksheet exports to CSV for reports and audits.
        </p>

        <h2>Built on real analyses, in the same tool</h2>
        <p>
          The evidence isn't imported from somewhere else — you fit the{" "}
          <Link to="/weibull-analysis-software">life models</Link>, replacement intervals, and
          degradation models in the same platform, from the same datasets. Teams work in a shared
          workspace, and single studies can be shared view-only with anyone, referenced evidence
          included. See a <Link to="/learn/censored-data-suspensions">worked look at the data side</Link>,
          or start from the built-in sample study.
        </p>
      </>
    ),
    band: {
      h2: "Your next RCM review could check itself.",
      p: "Start from the sample study and link your first decision to real evidence — free.",
    },
  },
  {
    path: "/reliability-block-diagram-software",
    title: "Reliability Block Diagram (RBD) Software — Cloud-Based | Reliafy",
    description:
      "Build reliability block diagrams in the browser: series, parallel, k-of-n, and standby structures with system reliability, MTTF, importance measures, and minimal cut sets.",
    eyebrow: "Reliability block diagrams",
    h1: "Build reliability block diagrams in the browser",
    lede:
      "Drag components onto a canvas, wire them in series, parallel, k-of-n, or standby, and read off system reliability, MTTF, and which block matters most — no desktop install.",
    hero: <RbdHero />,
    jsonld: (p) => softwareJsonLd("Reliafy — RBD software", p.description, p.path),
    body: (
      <>
        <h2>Every structure you actually use</h2>
        <p>
          Series and parallel, k-of-n voting groups, standby redundancy with its own standby life
          model, and nested sub-systems so a "pump skid" block can itself be a diagram. The canvas
          validates as you build — dangling blocks and impossible k-of-n configurations are flagged
          before you compute, not after.
        </p>

        <h2>Blocks backed by fitted models, not typed-in numbers</h2>
        <p>
          Each block links to a life model <Link to="/weibull-analysis-software">fitted from your
          own failure data</Link> — Weibull, Lognormal, Gamma, proportional hazards — rather than a
          reliability number typed in from a datasheet. When you refit a model with new data, every
          diagram that uses it reflects the update. Mixed time units across blocks are detected and
          flagged.
        </p>

        <h2>Outputs that point at the fix</h2>
        <p>
          System reliability over time, system MTTF, and minimal path and cut sets. Birnbaum and
          Fussell-Vesely importance rank which component is actually driving system unreliability —
          the difference between "improve something" and "improve bearing B, it accounts for most
          of the risk."
        </p>

        <h2>In the browser, shareable by link</h2>
        <p>
          Diagrams live in the cloud: no licence dongle, nothing to install, and a diagram can be
          shared view-only with anyone — the models its blocks reference come along automatically.
          Teams edit in a shared workspace. Self-host the open-source core if your system designs
          can't leave the building. New to the method? Start with the{" "}
          <Link to="/learn/mtbf-vs-mttf">MTBF vs MTTF primer</Link> or the built-in sample diagram.
        </p>
      </>
    ),
    band: {
      h2: "Model your system before it surprises you.",
      p: "Start with the sample diagram and swap in your own blocks — free.",
    },
  },
  {
    path: "/reliability-analysis-software",
    title: "Reliability Analysis Software — Open Source & Hosted | Reliafy",
    description:
      "An open reliability analysis platform: Weibull and life-data analysis, reliability block diagrams, RCM, degradation and RUL tracking, and fleet failure forecasting. AGPL, self-hostable, or hosted in the cloud.",
    eyebrow: "Reliability engineering platform",
    h1: "The open reliability analysis platform",
    lede:
      "One place for the whole chain: fit life models from failure data, build system diagrams, choose maintenance strategies, and track the fleet you're running today. Open source at the core; hosted when you want zero setup.",
    hero: <HeroPlot />,
    jsonld: (p) => softwareJsonLd("Reliafy", p.description, p.path),
    body: (
      <>
        <h2>From failure data to maintenance decisions</h2>
        <p>
          Reliability engineering isn't one calculation — it's a chain, and most tools only sell
          you one link. Reliafy covers the chain in one platform, so a dataset you upload once
          feeds every analysis downstream:
        </p>
        <ul>
          <li>
            <Link to="/weibull-analysis-software"><strong>Weibull &amp; life-data analysis</strong></Link> —
            fit Weibull, Lognormal, Exponential, Gamma, Normal, and proportional-hazards models to
            censored and truncated data, with confidence bounds, B-lives, and model ranking.
          </li>
          <li>
            <Link to="/reliability-block-diagram-software"><strong>Reliability block diagrams</strong></Link> —
            series, parallel, k-of-n, and standby structures computing system reliability, MTTF,
            importance measures, and cut sets from your fitted models.
          </li>
          <li>
            <Link to="/rcm-software"><strong>Evidence-linked RCM</strong></Link> — worksheets where
            every maintenance decision cites the analysis that justifies it, re-checked live as
            data changes.
          </li>
          <li>
            <strong>Maintenance strategy</strong> — cost-optimal preventive-replacement intervals,
            failure-finding intervals for hidden functions, and head-to-head design comparisons.
          </li>
          <li>
            <strong>Degradation &amp; RUL</strong> — fit wear paths to a failure threshold and track
            in-service items with remaining-useful-life predictions that tighten with every
            inspection.
          </li>
          <li>
            <strong>Fleet failure forecasting</strong> — "how many failures next year?" answered
            from your own life model and each item's current age, for spares and budget planning.
          </li>
        </ul>

        <h2>Genuinely open source</h2>
        <p>
          The full toolkit is AGPL-3.0 on{" "}
          <a href="https://github.com/Reliafy/reliafy" target="_blank" rel="noreferrer">GitHub</a> and
          self-hosts with one <code>docker compose</code> command — the statistical core builds on
          the <code>surpyval</code> library. Your data can stay on your hardware, permanently, with
          no feature gates on the analysis engine.
        </p>

        <h2>Or hosted, with the extras</h2>
        <p>
          Reliafy Cloud adds accounts, team workspaces with shared editing, view-only sharing of
          any analysis, and an AI assistant that fits models, builds diagrams, and drafts RCM
          studies from plain-language requests. Free tier to start;{" "}
          <Link to="/#pricing">Pro is US$19/month</Link>.
        </p>

        <h2>Learn the methods</h2>
        <ul>
          <li><Link to="/learn/weibull-analysis">Weibull analysis: a complete, practical guide</Link></li>
          <li><Link to="/learn/mtbf-vs-mttf">MTBF vs MTTF: the difference, and when each applies</Link></li>
          <li><Link to="/learn/censored-data-suspensions">Censored data and suspensions</Link></li>
          <li><Link to="/learn/weibull-analysis-in-excel">Weibull analysis in Excel — and where it breaks</Link></li>
          <li><Link to="/learn/b10-life">B10 life, with a worked example</Link></li>
        </ul>
      </>
    ),
    band: {
      h2: "One platform for the whole reliability chain.",
      p: "Open source if you want control. Hosted if you want it now.",
    },
  },
];
