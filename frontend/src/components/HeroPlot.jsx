// Hero illustration: a Weibull probability plot (the app's signature view).
// Pure SVG so it prerenders crisply with no image request.
export default function HeroPlot() {
  const W = 520, H = 340, padL = 46, padB = 36, padT = 34, padR = 18;
  const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB;
  const lerp = (a, b, t) => a + (b - a) * t;
  const fit = [{ x: x0, y: y1 - 10 }, { x: x1, y: y0 + 10 }];
  const seed = [0.05, -0.04, 0.02, -0.06, 0.03, 0.06, -0.02, 0.04, -0.03, 0.05, -0.01, 0.03, 0.05, -0.04, 0.03];
  const pts = seed.map((d, i) => {
    const t = (i + 0.7) / (seed.length + 0.4);
    return {
      x: lerp(fit[0].x, fit[1].x, t),
      y: lerp(fit[0].y, fit[1].y, t) + d * (H * 0.5) * (0.5 + Math.abs(t - 0.5)),
    };
  });
  const band = (sign) => {
    const n = 24, a = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      const lx = lerp(fit[0].x, fit[1].x, t);
      const ly = lerp(fit[0].y, fit[1].y, t);
      a.push([lx, ly + sign * (9 + Math.abs(t - 0.5) * 42)]);
    }
    return a;
  };
  const bandPath =
    "M " + band(-1).map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ") +
    " L " + band(1).reverse().map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ") + " Z";
  const yTicks = [["90", 0.06], ["50", 0.28], ["10", 0.52], ["2", 0.74], [".5", 0.92]];
  const xTicks = [["100", 0.08], ["1k", 0.42], ["10k", 0.76]];

  return (
    <svg className="hero-plot" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Weibull probability plot">
      <text x={padL} y={20} className="hp-title">WEIBULL PROBABILITY PLOT</text>
      {yTicks.map(([lab, fy], i) => {
        const y = lerp(y0, y1, fy);
        return (
          <g key={"y" + i}>
            <line x1={x0} y1={y} x2={x1} y2={y} className="hp-grid" />
            <text x={x0 - 8} y={y + 3.5} textAnchor="end" className="hp-tick">{lab}</text>
          </g>
        );
      })}
      {xTicks.map(([lab, fx], i) => {
        const x = lerp(x0, x1, fx);
        return <text key={"x" + i} x={x} y={y1 + 16} textAnchor="middle" className="hp-tick">{lab}</text>;
      })}
      <line x1={x0} y1={y0} x2={x0} y2={y1} className="hp-axis" />
      <line x1={x0} y1={y1} x2={x1} y2={y1} className="hp-axis" />
      <path d={bandPath} className="hp-band" />
      <line x1={fit[0].x} y1={fit[0].y} x2={fit[1].x} y2={fit[1].y} className="hp-fit" />
      {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="3.4" className="hp-dot" />)}
    </svg>
  );
}
