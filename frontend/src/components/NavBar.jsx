import { NavLink } from "react-router-dom";
import Logo from "./Logo.jsx";

// Instrument top bar: cobalt mark + wordmark on the left, mono-uppercase
// section links on the right. Routed sections use NavLink so the active
// section is highlighted.
const ROUTES = [
  { label: "Modelling", to: "/modelling" },
  { label: "RBDs", to: "/rbds" },
];

export default function NavBar() {
  return (
    <nav className="navbar">
      <div className="navbar-inner">
        <NavLink className="brand" to="/modelling">
          <Logo size={30} />
          <span className="brand-name">Reliafy</span>
        </NavLink>
        <div className="nav-links">
          {ROUTES.map((l) => (
            <NavLink
              key={l.label}
              to={l.to}
              className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}
            >
              {l.label}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  );
}
