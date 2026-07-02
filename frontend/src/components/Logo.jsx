// Reliafy mark — a stylised reliability hazard curve in a rounded cobalt
// square, matching the Instrument design system. Scales with the `size` prop.
export default function Logo({ size = 30 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 30 30"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="30" height="30" rx="9" fill="#2f6df6" />
      <path
        d="M5 9c3.5 0 3.5 11.5 7 11.5S15.5 4 19 4s3.5 9.3 7 9.3"
        stroke="#ffffff"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
