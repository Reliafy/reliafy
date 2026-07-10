import PublicNav from "../components/PublicNav.jsx";

// Privacy Policy for Reliafy Cloud. Honest and specific: what we collect, the
// exact subprocessors, and how to get data deleted. Self-hosted instances send
// us nothing.
export default function PrivacyPage() {
  return (
    <div className="landing">
      <PublicNav />
      <article className="blog-article">
        <header className="blog-article-head">
          <div className="blog-card-meta"><time>Effective 3 July 2026</time></div>
          <h1>Privacy Policy</h1>
        </header>
        <div className="blog-prose">
          <p>
            This policy covers <strong>Reliafy Cloud</strong>. If you self-host the
            open-source version, your data lives on your own infrastructure and none
            of it reaches us.
          </p>

          <h2>What we collect</h2>
          <ul>
            <li><strong>Account details:</strong> your email address and display name,
              via sign-in with email/password or Google.</li>
            <li><strong>Your content:</strong> the datasets (CSV files), fitted models,
              and reliability block diagrams you save.</li>
            <li><strong>Billing records:</strong> your plan, AI credit balance, and a
              ledger of credit grants and usage. Card details go directly to Stripe —
              we never see or store them.</li>
            <li><strong>AI conversations:</strong> when you use the assistant, your
              messages (and the data the assistant reads to act for you) are sent to
              our AI provider to generate the response. We don't store chat
              transcripts on our servers.</li>
            <li><strong>Operational logs:</strong> standard request logs (timestamps,
              endpoints, status codes) for reliability and debugging.</li>
          </ul>
          <p>We don't run advertising or third-party analytics trackers.</p>

          <h2>How we use it</h2>
          <p>
            Only to operate the Service: authenticating you, storing your work,
            processing payments, metering AI usage, and fixing problems. We never
            sell your data, and we don't use your datasets or AI conversations to
            train machine-learning models.
          </p>

          <h2>Who processes it (subprocessors)</h2>
          <ul>
            <li><strong>Google Cloud / Firebase</strong> — hosting (Cloud Run) and
              authentication.</li>
            <li><strong>MongoDB Atlas</strong> — the database holding your account and
              content.</li>
            <li><strong>Stripe</strong> — payment processing and subscription
              management.</li>
            <li><strong>OpenAI</strong> — processes assistant conversations to generate
              responses.</li>
          </ul>

          <h2>Where it lives and how long</h2>
          <p>
            Application data is stored in MongoDB Atlas and Google Cloud (our primary
            region is Australia). We keep your content for as long as your account
            exists. Deleting an item in the app removes it from the live database;
            deleting your account removes your content and profile.
          </p>

          <h2>Your rights</h2>
          <p>
            You can access and delete your content in the app at any time. To export
            everything, delete your account entirely, or ask what we hold about you,
            email <a href="mailto:hello@reliafy.com">hello@reliafy.com</a> and
            we'll action it promptly. If you're in a jurisdiction with specific data
            rights (GDPR, Australian Privacy Principles), we'll honour them.
          </p>

          <h2>Cookies and local storage</h2>
          <p>
            We use browser storage only for sign-in session tokens (Firebase
            Authentication) and small UI preferences (like whether the assistant
            panel is open). No advertising or cross-site tracking cookies.
          </p>

          <h2>Changes</h2>
          <p>
            If this policy changes materially we'll update this page and note the new
            effective date; for significant changes we'll email account holders.
          </p>

          <h2>Contact</h2>
          <p>
            Privacy questions or requests:{" "}
            <a href="mailto:hello@reliafy.com">hello@reliafy.com</a>.
          </p>
        </div>
      </article>
      <footer className="landing-foot"><span>© Reliafy</span></footer>
    </div>
  );
}
