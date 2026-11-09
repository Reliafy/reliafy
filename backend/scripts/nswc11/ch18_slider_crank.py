"""Chapter 18, Slider crank mechanisms (Revision A): Eq. 18-1 (p. 18-3).

Checked against the rendered page 18-3:
- λ_SC = λ_BE + λ_RD + λ_SE + λ_RI + λ_SM, every term and the total in
  failures per million operations.
- λ_BE from Chapter 7 (rolling bearings), λ_RD 0.001 failures per million hours
  for rod fracture (p. 18-9; Chapter 20 if the rod is critical), λ_SE from
  Section 3.2 (gaskets and static seals), λ_RI from Section 3.3 (rings and
  dynamic seals), λ_SM from Chapter 9, Section 9.3 (the slider's wear).

Readings chosen (each in the report):
- Units: Eq. 18-1 says every term is per million operations, but the parts'
  own models are per million hours (bearings, seals, the rod's 0.001, p. 18-9)
  or per million cycles (Chapter 9). The record is per million hours: the
  slider's wear is multiplied by the crank's operations (revolutions) an hour
  (the handbook's rule, pp. 12-10, 12-16), and the per-hour parts added as they
  are. The same operations an hour set the bearings' speed (rpm = ops/h ÷ 60).
- Sliding (journal) bearings: Section 18.3.1 describes them (Eq. 18-2 to 18-8:
  shear stress, viscosity, the νn/P number, PV) but gives no failure rate
  model, sending the reader to Chapter 7's rolling bearings. Only rolling
  bearings are modelled; Eq. 18-2 to 18-8 are left out.
- λ_SM: Chapter 9 has side-load and axial-load actuator records; the slider
  uses the side-load one, since a crank's connecting rod pushes the slider
  sideways against its guide as it swings (a reading: Chapter 18 doesn't say).
- The rod uses the handbook's 0.001 estimate; Chapter 20's shaft model is the
  handbook's alternative "if deemed critical".
"""

from backend.scripts.nswc11.common import base, mode, num, positive, record, refuse, uses

_FAILURE_MODES = [
    "Linkage moves the wrong way: bearing parts separate and jam",
    "Restricted linkage travel: excess load with bearing wear; seal leakage",
    "Broken linkage: fatigue of a link",
    "Linkage out of alignment: deformed bearing",
    "Poor linkage response: lubricant film too thin; seal leakage",
]


def _count(name: str, label: str, help: str) -> dict:
    return num(name, label, "", [refuse(min=0, why="a count can't be negative")], symbol="n", page="18-3", help=help)


def _as_written(what: str, unit: str) -> str:
    if unit == "million hours":
        return f"{what} is in failures per million hours, so it adds as it is (Eq. 18-1 labels it per million operations)."
    return (f"{what} is in failures per {unit}: × the crank's operations an hour, so it adds to the per-hour parts "
            "(pp. 12-10, 12-16).")


RECORDS = [
    record(
        "slider-crank", "Slider crank mechanism", "mechanism", 18, "18.3 Model development", "18-1", "18-3",
        "λ_SC = λ_BE + λ_RD + λ_SE + λ_RI + λ_SM · ops/h",
        "A slider crank's failure rate is the sum of its parts: its bearings, its connecting rods, its seals and "
        "gaskets, its rings and other dynamic seals, and the wear of the slider on its sliding surface.",
        inputs=[
            num("ops_per_hour", "Crank operations (revolutions) per hour", "per hour",
                [positive("a crank that never turns isn't rated by this model")], symbol="ops/h", page="18-3",
                help="One operation is one crank revolution (one slider stroke and return). Converts the slider's "
                     "wear per million cycles to per hour and sets the bearings' speed (rpm = this ÷ 60)."),
            _count("n_BE", "Number of rolling bearings", "One at each rotating joint (Figure 18.1)."),
            _count("n_RD", "Number of rods or links", "Each 0.001 failures per million hours for fracture."),
            _count("n_SE", "Number of static seals and gaskets", "O-rings and flat seals (Section 3.2)."),
            _count("n_RI", "Number of rings and dynamic seals", "Piston rings and other dynamic seals (Section 3.3)."),
        ],
        modes=[
            uses("bearings", "Bearings (each)", "bearing-rolling-load-rating", symbol="λ_BE", count="n_BE",
                 bind={"n": "ops_per_hour / 60"},
                 note=_as_written("Chapter 7's bearing rate", "million hours")),
            mode("rods", "Rods and shafts (fracture, each)",
                 base("λ_RD", "Rod fracture failure rate", "18-9", value=0.001), symbol="λ_RD", count="n_RD",
                 note=_as_written("The handbook's 0.001 rod estimate (p. 18-9)", "million hours")),
            uses("seals", "Seals and gaskets (each)", "seal-static", symbol="λ_SE", count="n_SE",
                 note=_as_written("Chapter 3's static seal rate", "million hours")),
            uses("rings", "Rings and dynamic seals (each)", "seal-dynamic", symbol="λ_RI", count="n_RI",
                 note=_as_written("Chapter 3's dynamic seal rate", "million hours")),
            uses("slider", "Slider mechanism (wear)", "actuator-side-load", symbol="λ_SM", scale="ops_per_hour",
                 scale_label="operations an hour",
                 note=_as_written("Chapter 9's side-load actuator rate (the slider wears under the rod's side "
                                  "thrust)", "million cycles")),
        ],
        notes=("Rolling bearings only: the chapter describes sliding bearings (Eq. 18-2 to 18-8) but gives them no "
               "failure rate. The rod takes the handbook's 0.001 estimate; Chapter 20's shaft model is its "
               "alternative for a critical rod."),
        failure_modes=_FAILURE_MODES,
    ),
]
