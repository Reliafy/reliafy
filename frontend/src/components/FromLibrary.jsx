import { Link } from "react-router-dom";
import { libraryPath } from "../libraries.js";

// A copy made from a library (Use this data / Use this model) says where it came from, quietly:
// "From the library <name> (version n)". ``from``: the item's ``from_library``.
export default function FromLibrary({ from, className = "" }) {
  if (!from?.library_id) return null;
  return (
    <p className={"from-library" + (className ? ` ${className}` : "")}>
      From the library <Link to={libraryPath(from.library_id)}>{from.library_name || "a library"}</Link>
      {from.version ? ` (version ${from.version})` : ""}
    </p>
  );
}
