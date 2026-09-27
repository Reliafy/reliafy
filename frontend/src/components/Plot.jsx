// The chart component, bound to Plotly's *basic* build (scatter, bar and pie
// traces on cartesian axes — every chart the app draws). The default
// ``react-plotly.js`` export bundles the complete, unminified plotly.js
// (~11 MB of source, ~1.5 MB gzipped); the basic build is ~0.3 MB gzipped.
// Using another trace type (heatmap, box, histogram, …) needs a larger build.
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";

const Plot = createPlotlyComponent(Plotly);
export default Plot;
