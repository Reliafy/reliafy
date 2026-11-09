"""Chapter 23, Miscellaneous parts (Revision B): the typical failure rates the
chapter gives for passive parts, with its service factor tables, and the power
screw, Eq. 23-1.

Checked against the rendered pages 23-3 to 23-22. Most of these parts have no
numbered equation: the chapter states one typical rate in its text, so those
records cite the section (e.g. "§23.3.2") as their equation.
- Axle (p. 23-3): "a typical failure rate for a shaft will be 0.01 failures/million
  hours", under the axle heading; read as the axle's rate. For small axles and shafts
  the handbook points to Chapter 20 (the shaft model).
- Bolt (p. 23-4): 0.12 per million hours for the bolted system (washers, nuts, thread
  locking), × Table 23-3 (loading × vibration). The handbook says to adjust for "the
  number of bolts being used" (p. 23-5): a count input, default 1.
- Bushing (p. 23-6): 0.72; cam mechanism (p. 23-8): 6.1; keys and pins (p. 23-13): 0.35;
  rivet (p. 23-18): 0.08; all per million hours.
- Rivet (p. 23-18): "slightly out-of-round holes can increase the failure rate by a
  factor of 10" is kept as a hole-quality choice (1 or 10); the text gives it as an
  upper figure ("can"), so the model uses 10 only when the holes are out of round.
- Fitting (p. 23-9): 1.3 threaded, 2.4 quick disconnect. A seal (Chapter 3) or a
  shut-off valve (Chapter 6) in the fitting is a separate part.
- Flywheel (p. 23-11): 0.2 × Table 23-8 (driven machinery × torque and velocity).
- Hinge (p. 23-12): 0.5 failures per million cycles (metal or living hinge). A hinge
  spring is a separate part (Chapter 4); it isn't added here because its rate is per
  hour and the hinge's per cycle.
- Pillow block (p. 23-14): 5.0 failures per million revolutions, kept per million
  cycles (one revolution, one cycle). The handbook's alternative, the bearing's L10
  life adjusted by Chapter 7's procedures, is a second record that uses the Chapter 7
  bearing model.
- Power screw, Eq. 23-1 (p. 23-15): λ_PS / λ_PS,B = (L_A / L_S)³, λ_PS,B from the screw's
  published life; the chapter gives no number for it, so it's an input.
- Setscrew (p. 23-20): 0.35 × Table 23.14 (environment × humidity).
- Wire rope (p. 23-22): 17.5 failures per million operations.
- Left out: rivet stresses (Eqs. 23-2 to 23-4) and wire rope bearing pressure (23-5)
  are design checks, not factors.
"""

from backend.scripts.nswc11.common import base, choice, factor, mode, num, positive, record, table, uses


def _typical(slug: str, name: str, equipment: str, section: str, page: str, symbol: str, rate: float,
             words: str, failure_modes: list[str], rate_unit: str = "per_million_hours",
             notes: str | None = None) -> dict:
    """A part with one typical rate stated in the text and no factors."""
    return record(
        slug, name, equipment, 23, section, f"§{section.split(' ')[0]}", page, f"{symbol} = {rate:g}", words,
        inputs=[],
        modes=[mode("part", name, base(symbol, f"Typical failure rate of a {name.lower()}", page, value=rate),
                    symbol=symbol)],
        rate_unit=rate_unit, failure_modes=failure_modes, notes=notes,
    )


BOLT_SERVICE = {
    "light": {"normal": 1.00, "high": 1.50},
    "medium": {"normal": 1.25, "high": 1.88},
    "heavy": {"normal": 1.67, "high": 2.50},
    "very_heavy": {"normal": 2.50, "high": 3.75},
}

FLYWHEEL_SERVICE = {
    "uniform": {"normal_low": 1.1, "normal_high": 1.3, "high_low": 1.2, "high_high": 1.4},
    "light": {"normal_low": 1.2, "normal_high": 1.4, "high_low": 1.3, "high_high": 1.5},
    "medium": {"normal_low": 1.3, "normal_high": 1.5, "high_low": 1.4, "high_high": 1.6},
    "heavy": {"normal_low": 1.4, "normal_high": 1.6, "high_low": 1.5, "high_high": 1.7},
}

SETSCREW_SERVICE = {
    "normal": {"low": 1.0, "high": 1.2},
    "random": {"low": 1.2, "high": 1.4},
    "continuous": {"low": 1.5, "high": 1.8},
}

RECORDS = [
    _typical("axle", "Axle", "shaft", "23.2.2 Axle failure rate", "23-3", "λ_AX", 0.01,
             "An axle (a non-rotating member carrying wheels or pulleys, no torque) has a typical failure rate of "
             "0.01 failures per million hours; the parts mounted on it are rated on their own.",
             ["Fatigue at a stress raiser from shock or vibration", "Bent axle from bending stresses",
              "Unstable rotation from vibration", "Uneven rotation from a loose mounting"],
             notes="A stress-strength analysis gives a better rate; for small axles and shafts use Chapter 20."),
    record(
        "bolt", "Bolted joint", "fastener", 23, "23.3.2 Bolt failure rate", "§23.3.2", "23-4",
        "λ_BO = 0.12 · C_SF × number of bolts",
        "A bolt, with its washers, nuts and thread locking, has a typical failure rate of 0.12 failures per million "
        "hours, scaled up for heavier loading and continuous high vibration, for each bolt in the joint.",
        inputs=[
            choice("loading", "Loading", [
                ("light", "Light (office equipment)"), ("medium", "Medium (compressors, large motors)"),
                ("heavy", "Heavy (production equipment, trucks, aircraft, ships)"),
                ("very_heavy", "Very heavy (construction equipment, tanks)"),
            ], default="light", default_basis="neutral", symbol="C_SF", page="23-4"),
            choice("vibration", "Vibration", [("normal", "Normal vibration"),
                                              ("high", "Continuously high vibration")],
                   default="normal", default_basis="neutral", symbol="C_SF", page="23-4"),
            num("n_bolts", "Number of bolts", "", [positive("a joint has at least one bolt")], default=1,
                default_basis="neutral", page="23-5", help="The handbook: adjust for the number of bolts used."),
        ],
        modes=[mode("bolts", "Bolts", base("λ_BO,B", "Typical failure rate of a bolt", "23-4", value=0.12), [
            factor("C_SF", "Service (loading and vibration)", "23-4",
                   table=table(["loading", "vibration"], BOLT_SERVICE), source="Table 23-3",
                   words="heavier loading and vibration"),
        ], symbol="λ_BO", count="n_bolts")],
        failure_modes=["Loose bolt (too little preload, shock or vibration)",
                       "Plastic deformation (overload, excessive bearing pressure)",
                       "Sheared bolt (fatigue from repeated loading, vibration)",
                       "Stripped threads (excessive preload)"],
        notes="Chapter 16 has the detailed threaded fastener model.",
    ),
    _typical("bushing", "Bushing", "bearing", "23.4.2 Bushing failure rate", "23-6", "λ_BU", 0.72,
             "A bushing has a typical failure rate of 0.72 failures per million hours, to be adjusted from "
             "experience with the application.",
             ["Loose on the shaft (vibration)", "Corrosion (dissimilar materials or fluid)",
              "Structural failure (misalignment, excessive load)", "Damaged set screw (over-tightening)",
              "Loss of radial or axial movement (loss of lubrication)"],
             notes="The handbook points to Chapter 7's plain bearing procedures for a detailed estimate."),
    _typical("cam-mechanism", "Cam mechanism", "mechanism", "23.5.2 Cam mechanism failure rate", "23-8", "λ_CM",
             6.1,
             "A cam mechanism has a typical failure rate of 6.1 failures per million hours; its speed, friction, "
             "wear and materials change it.",
             ["Cam follower error (excessive pressure angle, high torque while the follower accelerates)",
              "Drive speed fluctuation (load changes, backlash)", "Loose shaft and cam contact (loose shaft pin)",
              "Worn cam and follower contact (excessive load, binding)",
              "Cam or follower fracture (excessive load)"],
             notes="Chapter 9's wear equations can refine it."),
    record(
        "fitting", "Fluid fitting", "pipe", 23, "23.6.2 Fitting failure rate", "§23.6.2", "23-9",
        "λ_FI = 1.3 (threaded) or 2.4 (quick disconnect)",
        "A fluid fitting has a typical failure rate of 1.3 failures per million hours if threaded and 2.4 if a "
        "quick disconnect.",
        inputs=[choice("fitting_type", "Fitting type", [("threaded", "Threaded"),
                                                         ("quick_disconnect", "Quick disconnect")],
                       symbol="λ_FI", page="23-9")],
        modes=[mode("fitting", "Fitting", base("λ_FI", "Typical failure rate of a fitting", "23-9",
                                               table=table("fitting_type", {"threaded": 1.3,
                                                                            "quick_disconnect": 2.4})),
                    symbol="λ_FI")],
        failure_modes=["Seepage (damaged sleeve, ferrule or O-ring, wrong assembly)",
                       "Fractured plastic housing (shock, vibration)", "Leakage from fluid incompatibility",
                       "Damaged flare joint from wrong tightening", "Damaged seal from fluid too hot"],
        notes=("NPT ports in high-pressure hydraulics fail more often than this. A seal (Chapter 3) or shut-off "
               "valve (Chapter 6) in the fitting is a separate part."),
    ),
    record(
        "flywheel", "Flywheel", "other", 23, "23.7.2 Flywheel failure rate", "§23.7.2", "23-11",
        "λ_FW = 0.2 · C_SF",
        "A flywheel has a typical failure rate of 0.2 failures per million hours, scaled up for shock from the "
        "driven machinery, higher torque and higher speed.",
        inputs=[
            choice("shock", "Driven machinery", [("uniform", "Uniform"), ("light", "Light shock"),
                                                 ("medium", "Medium shock"), ("heavy", "Heavy shock")],
                   symbol="C_SF", page="23-11"),
            choice("duty", "Torque and velocity", [
                ("normal_low", "Normal torque, low velocity"), ("normal_high", "Normal torque, high velocity"),
                ("high_low", "High torque, low velocity"), ("high_high", "High torque, high velocity"),
            ], symbol="C_SF", page="23-11"),
        ],
        modes=[mode("flywheel", "Flywheel", base("λ_FW,B", "Base failure rate of a flywheel", "23-11", value=0.2), [
            factor("C_SF", "Service", "23-11", table=table(["shock", "duty"], FLYWHEEL_SERVICE), source="Table 23-8",
                   words="shock, torque and speed"),
        ], symbol="λ_FW")],
        failure_modes=["Loosened from the shaft (broken shaft-wheel connection)", "Fracture (centrifugal forces)",
                       "System vibration (unbalanced flywheel)"],
    ),
    _typical("hinge", "Hinge", "mechanism", "23.8.2 Hinge failure rate", "23-12", "λ_HI", 0.5,
             "A metal or living hinge has a typical failure rate of 0.5 failures per million cycles in normal use.",
             ["Bent pin (excessive loading)", "Weak spring (shock loads)", "Damaged plating (corrosion)",
              "Noisy hinge (contaminants, bent pin, no lubrication)", "Jammed hinge (excessive loading, damaged pin)"],
             rate_unit="per_million_cycles",
             notes="A spring-loaded hinge's spring is a separate part (Chapter 4), rated per hour."),
    _typical("key-pin", "Key or pin", "coupling", "23.9.2 Key and pin failure rate", "23-13", "λ_KP", 0.35,
             "A key or pin securing a part on a shaft has a typical failure rate of 0.35 failures per million hours.",
             ["Sheared pin or key (loose part on the shaft)", "Loose pin or key (enlarged holes)",
              "Damaged pin (shock, vibration)", "Damaged keyway (excessive axial load)"]),
    _typical("pillow-block", "Pillow block", "bearing", "23.10.2 Pillow block failure rate", "23-14", "λ_PB", 5.0,
             "A pillow block (a bearing in its housing) has a typical failure rate of 5.0 failures per million "
             "revolutions.",
             ["Worn bearing race (side loading, misalignment)",
              "Bearing seizure (lost lubricant, excessive speed, heat)", "Loss of lubricant (seal leakage)",
              "Damaged housing (shock, vibration)", "Loose shaft coupling (loose set screw)"],
             rate_unit="per_million_cycles",
             notes="The handbook gives this per million revolutions: one revolution is one cycle here."),
    record(
        "pillow-block-from-l10", "Pillow block (from its bearing's L10 life)", "bearing", 23,
        "23.10 Pillow block", "§23.10", "23-13", "λ_PB = λ_BE (Chapter 7, Eq. 7-5)",
        "A pillow block's bearing is rated by its L10 life; the handbook says to adjust that life for the "
        "application with Chapter 7's procedures, so its failure rate is the Chapter 7 bearing model's.",
        inputs=[],
        modes=[uses("bearing", "Pillow block bearing", "bearing-rolling-known-l10", symbol="λ_BE",
                    note="Chapter 7's rolling bearing model from a known L10 life, as section 23.10 directs.")],
        failure_modes=["Worn bearing race (side loading, misalignment)",
                       "Bearing seizure (lost lubricant, excessive speed, heat)", "Loss of lubricant (seal leakage)",
                       "Damaged housing (shock, vibration)", "Loose shaft coupling (loose set screw)"],
        notes="Misalignment of the block on its shaft isn't in the bearing model; the handbook says to consider it.",
    ),
    record(
        "power-screw", "Power screw (ball screw)", "mechanism", 23, "23.11 Power screws", "23-1", "23-15",
        "λ_PS = λ_PS,B · (L_A / L_S)³",
        "A ball screw's failure rate starts at the rate from its published life and goes with the cube of the "
        "load it carries against its rated load, as a ball bearing's does.",
        inputs=[
            num("lam_PSB", "Failure rate from the screw's published life", "failures per million hours",
                [positive("a failure rate is more than zero")], symbol="λ_PS,B", page="23-15",
                help="The handbook gives no number: take it from the maker's rated life."),
            num("L_A", "Equivalent load in service", "lbf", [positive("the screw carries a load")], symbol="L_A",
                page="23-15"),
            num("L_S", "Basic dynamic load rating", "lbf", [positive("a load rating is more than zero")],
                symbol="L_S", page="23-15", help="The load it is rated to carry for a million inches of travel."),
        ],
        modes=[mode("screw", "Power screw", base("λ_PS,B", "Rate from the published life", "23-15", expr="lam_PSB",
                                                 equation="23-1"), [
            factor("C_L", "Load against rating", "23-15", expr="(L_A / L_S) ** 3", equation="23-1",
                   words="more load against its rating"),
        ], symbol="λ_PS")],
        failure_modes=["Screw bonded to nut (lost lubrication, excessive pressure)", "Scored screw (misalignment)",
                       "Fractured nut (excessive pressure-velocity)",
                       "Worn threads (contaminants, loading)"],
        notes="The handbook's preferred route without experience: rate the parts with Chapters 9 and 16.",
    ),
    record(
        "rivet", "Riveted joint", "other", 23, "23.12.2 Rivet failure rate", "§23.12.2", "23-18",
        "λ_RI = 0.08 · C_H",
        "A riveted joint built to the maker's specification has a typical fatigue failure rate of 0.08 failures per "
        "million hours; slightly out-of-round holes can make it ten times higher.",
        inputs=[choice("holes", "Rivet holes", [("round", "Round, as specified"),
                                                ("out_of_round", "Slightly out of round")],
                       default="round", default_basis="neutral", symbol="C_H", page="23-18")],
        modes=[mode("rivet", "Rivet", base("λ_RI,B", "Typical fatigue failure rate of a riveted joint", "23-18",
                                           value=0.08), [
            factor("C_H", "Hole quality", "23-18", table=table("holes", {"round": 1.0, "out_of_round": 10.0}),
                   words="out-of-round holes"),
        ], symbol="λ_RI")],
        failure_modes=["Rivet shears through", "Rivet or plate crushes", "Plate tears from the hole to its edge",
                       "Plate shears along two lines to its edge", "Plate tears between rivets",
                       "Plate fails in tension"],
        notes="The factor of 10 for out-of-round holes is the handbook's 'can increase … by a factor of 10'.",
    ),
    record(
        "setscrew", "Setscrew", "fastener", 23, "23.13.2 Setscrew failure rate", "§23.13.2", "23-20",
        "λ_SS = 0.35 · C_SF",
        "A setscrew has a typical failure rate of 0.35 failures per million hours, scaled up for shock and "
        "vibration and for high humidity.",
        inputs=[
            choice("environment", "Operating environment", [
                ("normal", "Normal duty"), ("random", "Random shock and vibration"),
                ("continuous", "Continuous shock and vibration"),
            ], default="normal", default_basis="neutral", symbol="C_SF", page="23-20"),
            choice("humidity", "Humidity", [("low", "Low humidity"), ("high", "High humidity")],
                   default="low", default_basis="neutral", symbol="C_SF", page="23-20"),
        ],
        modes=[mode("setscrew", "Setscrew", base("λ_SS,B", "Typical failure rate of a setscrew", "23-20",
                                                 value=0.35), [
            factor("C_SF", "Service (environment and humidity)", "23-20",
                   table=table(["environment", "humidity"], SETSCREW_SERVICE), source="Table 23.14",
                   words="shock, vibration and humidity"),
        ], symbol="λ_SS")],
        failure_modes=["Collar or hub moves along the shaft (loosened by shock and vibration)",
                       "Collar or hub turns on the shaft (loosened by shock and vibration)",
                       "Damaged setscrew (wrong installation torque, corrosion)"],
    ),
    _typical("wire-rope", "Wire rope", "other", "23.14.2 Wire rope failure rate", "23-22", "λ_WR", 17.5,
             "A wire rope chosen with the published safety factors has a typical failure rate of 17.5 failures per "
             "million operations.",
             ["Breakage (abrupt starts and stops)",
              "Fatigue (sharp bends over sheaves, vibration, installation, lost lubricant)",
              "Crushed wires (external forces)", "Damaged rope (sheave misalignment)"],
             rate_unit="per_million_operations"),
]
