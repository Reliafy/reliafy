// The site's positioning in one place: the home page's search title and
// description, the hero, and the structured data that describes Reliafy.
// prerender-entry.jsx and Landing.jsx read it; index.html (the app shell's
// default head) repeats the title and description, and siteCopy.test.js
// keeps the two in step.
//
// Lead with what Reliafy changes for asset-intensive organisations, not with
// the price: the Free plan is real and stays on the pricing section, but a
// search result that opens with "free" reads like a free calculator. Keep the
// search terms people use (Weibull, life data analysis, RBD, RCM) in the
// description; the per-tool pages keep their own keyword titles.

export const SITE = "https://reliafy.com";

// Search result title (<= 60 characters) and description (<= 155).
export const HOME_TITLE = "Reliafy — Transforming asset management with reliability";
export const HOME_DESCRIPTION =
  "Weibull and life data analysis, RBDs, RCM and failure forecasts for asset-intensive organisations: know when to replace, inspect and restock.";

export const HERO = {
  eyebrow: "Reliability engineering for asset-intensive organisations",
  h1: "Transform how you manage your assets.",
  lede:
    "Reliafy turns failure and condition data into decisions: when to replace, when to inspect and how many spares to hold. Life data and Weibull analysis, reliability block diagrams, RCM and fleet forecasts, in one place.",
};

// One sentence about Reliafy for structured data and other summaries.
export const ABOUT =
  "Reliability engineering software that turns failure and condition data into asset decisions: when to replace, when to inspect and which spares to hold.";

// Structured data for the home page: who publishes Reliafy, and what it is.
// The free tier stays in the offers (it is real); the lead is the product.
export function homeJsonLd() {
  return [
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: "Reliafy",
      url: SITE,
      logo: `${SITE}/apple-touch-icon.png`,
      description: ABOUT,
      sameAs: ["https://github.com/Reliafy"],
    },
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: "Reliafy",
      description: ABOUT,
      url: SITE,
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web browser",
      offers: [
        { "@type": "Offer", price: "0", priceCurrency: "USD", description: "Cloud Free plan" },
        { "@type": "Offer", price: "19", priceCurrency: "USD", description: "Pro plan, per month" },
      ],
      license: "https://www.gnu.org/licenses/agpl-3.0.html",
      publisher: { "@type": "Organization", name: "Reliafy", url: SITE },
    },
  ];
}
