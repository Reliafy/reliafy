"""Chapter 5, Solenoids, contactors (Revision E): the solenoid (Eq. 5-1) and the
contactor (Eqs. 5-6, 5-7 and 5-8: AC resistive, AC inductive and DC loads).

Checked against the rendered pages 5-5 to 5-15:
- Eq. 5-1 (p. 5-5): λ_SO = λ_SO,B · C_T · C_K · C_S in failures per million hours,
  with λ_SO,B = 2.77 failures per million operations and C_S the use rate in
  operations an hour (operations/min × 60): per operation × operations an hour
  gives per hour, so the record's unit is per million hours as the page states.
- C_T (Eq. 5-2, Figure 5.2, p. 5-10): (1/1.5^t)³ with t = ((T_R − T_O) − 20)/10;
  1 at T_R − T_O = 20 °C and about 11.4 at 0, as plotted. The figure covers
  T_R − T_O from −50 to 60 °C.
- C_K (Table 5-2, p. 5-8): by environment and by load and stroke.
- Contactor (p. 5-9): base 1.10 (AC resistive), 3.60 (AC inductive), 2.5 (DC)
  failures per million operations. AC: C_V = (V_o/V_r)^0.75 (Figure 5.3, p. 5-11),
  C_I = 3.50 (I_o/I_r)^1.14 (Figure 5.4, p. 5-12), C_PF = 4.0 PF² (Figure 5.5,
  p. 5-13); DC: C_V = (V_o/V_r)^1.33 (Figure 5.6, p. 5-14), C_I = 4.20 (I_o/I_r)^1.30
  (Figure 5.7, p. 5-15). The curves agree with the formulas.
- C_PF rises with the power factor (4.0 at PF = 1, 1.0 at 0.5): as printed and as
  plotted, though a lower power factor is usually the harder duty. Reported, not
  changed.
- Left out: Eq. 5-5 (p. 5-8), the general λ_C,B · ν^m · I^n, whose constants m and n
  the handbook doesn't give; Eq. 5-3's coil self-heating (an aid to find T_O, not a
  failure rate).
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, num, positive, record, refuse, table, warn,
)

_SOLENOID_MODES = [
    "Coil burnout: too little heat sink, inrush current, voltage surges, excessive cycling, high ambient temperature",
    "Failure to operate: coil resistance rises with heat; mechanical jamming of the plunger",
    "Open or shorted winding: moisture, voltage overload, vibration at the terminations",
    "Plunger (armature) failure: hammering from too much force for the load",
    "Slow pull-in or drop-out: too little force for the load, a jammed or damaged return spring",
]

_CONTACTOR_MODES = [
    "Contact damage from arcing (excessive load voltage); failure when contact resistance doubles",
    "Coil and operating mechanism failures as for a solenoid",
]

_LOADS = [("normal_min", "Normal load or torque, minimum stroke or rotation"),
          ("normal_ext", "Normal load or torque, extended stroke or rotation"),
          ("high_min", "High load or torque, minimum stroke or rotation"),
          ("high_ext", "High load or torque, extended stroke or rotation")]

RECORDS = [
    record(
        "solenoid", "Solenoid (linear or rotary)", "solenoid", 5, "5.3 Failure rate of solenoid assembly", "5-1",
        "5-5", "λ_SO = λ_SO,B · C_T · C_K · C_S",
        "A solenoid's failure rate starts at 2.77 failures per million operations, times how many operations it "
        "makes an hour, and is scaled by how hot its coil runs against its insulation rating and by the shock, "
        "load and stroke of its duty.",
        inputs=[
            num("T_R", "Rated temperature of the solenoid (its insulation class)", "°C",
                [refuse(min=-273.15, why="below absolute zero")], symbol="T_R", page="5-5",
                help="Insulation classes (p. 5-5): A 105, B 130, F 155, H 180, C 220 °C."),
            num("T_O", "Operating temperature of the solenoid coil", "°C",
                [refuse(min=-273.15, why="below absolute zero")], symbol="T_O", page="5-6",
                help="Eq. 5-3 (p. 5-7) estimates the coil's self-heating from the current and on-time."),
            choice("environment", "Operating environment", [
                ("uniform", "Uniform"), ("light_shock", "Light shock"), ("medium_shock", "Medium shock"),
                ("heavy_shock", "Heavy shock"),
            ], default="uniform", default_basis="typical", symbol="C_K", page="5-8"),
            choice("duty", "Load and stroke", _LOADS, default="normal_min", default_basis="typical", symbol="C_K",
                   page="5-8"),
            num("ops_per_min", "Use rate", "operations/min", [positive("a solenoid that never operates isn't rated")],
                symbol="C_S", page="5-5"),
        ],
        derived=[
            derived("dT", "Rated minus operating temperature", "T_R - T_O", "°C", "T_R − T_O", "5-10",
                    limits=[warn(min=-50, max=60, why="Figure 5.2 covers T_R − T_O from −50 to 60 °C",
                                 page="5-10")]),
            derived("t", "Temperature exponent", "(dT - 20) / 10", "", "t", "5-6", "5-2"),
            derived("C_S", "Operations an hour", "ops_per_min * 60", "operations/hour", "C_S", "5-5"),
        ],
        modes=[mode("solenoid", "Solenoid (coil and plunger)",
                    base("λ_SO,B", "Base failure rate of a solenoid (per million operations)", "5-5", value=2.77),
                    [
                        factor("C_T", "Coil temperature", "5-10", expr="(1 / 1.5 ** t) ** 3", equation="5-2",
                               source="Figure 5.2", words="a hotter coil for its insulation rating"),
                        factor("C_K", "Application service", "5-8", table=table(["environment", "duty"], {
                            "uniform": {"normal_min": 1.1, "normal_ext": 1.3, "high_min": 1.2, "high_ext": 1.4},
                            "light_shock": {"normal_min": 1.2, "normal_ext": 1.4, "high_min": 1.3, "high_ext": 1.5},
                            "medium_shock": {"normal_min": 1.3, "normal_ext": 1.5, "high_min": 1.4, "high_ext": 1.6},
                            "heavy_shock": {"normal_min": 1.4, "normal_ext": 1.6, "high_min": 1.5, "high_ext": 1.7},
                        }), source="Table 5-2", words="shock, a high load, a long stroke"),
                        factor("C_S", "Use rate (operations an hour)", "5-5", expr="C_S",
                               words="operating more often"),
                    ], symbol="λ_SO")],
        notes=("Sum the solenoid with its other parts for the assembly (p. 5-1): its return spring (Chapter 4), "
               "the valve or actuator it drives (Chapters 6, 9), a rotary solenoid's bearing (Chapter 7) and, in a "
               "relay, its contactor. An on-time over 5 minutes in a single pulse counts as continuous duty (p. 5-5)."),
        failure_modes=_SOLENOID_MODES,
    ),
    record(
        "contactor", "Contactor (relay contacts)", "solenoid", 5, "5.4 Failure rate of contactor assembly",
        "5-6, 5-7, 5-8", "5-9",
        "λ_C = λ_C,B · C_V · C_I (AC resistive, Eq. 5-6; DC, Eq. 5-8), λ_C = λ_C,B · C_V · C_I · C_PF "
        "(AC inductive, Eq. 5-7)",
        "A contactor's failure rate per million operations starts at 1.10 for an AC resistive load, 3.60 for an AC "
        "inductive load or 2.5 for a DC load, and is scaled by its voltage and current against their ratings (and, "
        "for an inductive load, by the power factor).",
        inputs=[
            choice("load", "Load type", [("ac_resistive", "AC, resistive"), ("ac_inductive", "AC, inductive"),
                                         ("dc", "DC")], symbol="λ_C,B", page="5-9"),
            num("V_o", "Operating voltage", "V", [positive("a voltage is more than zero")], symbol="V_o", page="5-11"),
            num("V_r", "Rated voltage", "V", [positive("a rating is more than zero")], symbol="V_r", page="5-11"),
            num("I_o", "Operating current", "A", [positive("a current is more than zero")], symbol="I_o", page="5-12"),
            num("I_r", "Rated current", "A", [positive("a rating is more than zero")], symbol="I_r", page="5-12"),
            num("PF", "Power factor (AC inductive loads)", "", [
                refuse(min=0, max=1, why="a power factor is 0 to 1"),
            ], default=0, default_basis="neutral", symbol="PF", page="5-13",
                help="Only for an AC inductive load; leave at 0 otherwise."),
        ],
        derived=[
            derived("V_ratio", "Operating ÷ rated voltage", "V_o / V_r", "", "V_o/V_r", "5-11"),
            derived("I_ratio", "Operating ÷ rated current", "I_o / I_r", "", "I_o/I_r", "5-12"),
        ],
        checks=[
            check("PF > 0", "An AC inductive load needs its power factor", "5-13", severity="refuse",
                  when="load == 'ac_inductive'"),
            check("0.25 <= PF", "Figure 5.5 covers power factors from 0.25 to 1.0", "5-13",
                  when="load == 'ac_inductive' and PF > 0"),
            check("0.1 <= V_ratio <= 1.3", "Figure 5.3 covers V_o/V_r from 0.1 to 1.3", "5-11", when="load != 'dc'"),
            check("0.1 <= I_ratio <= 1.3", "Figure 5.4 covers I_o/I_r from 0.1 to 1.3", "5-12", when="load != 'dc'"),
            check("0.1 <= V_ratio <= 1.2", "Figure 5.6 covers V_o/V_r from 0.1 to 1.2", "5-14", when="load == 'dc'"),
            check("0.1 <= I_ratio <= 1.2", "Figure 5.7 covers I_o/I_r from 0.1 to 1.2", "5-15", when="load == 'dc'"),
        ],
        modes=[mode("contacts", "Contacts",
                    base("λ_C,B", "Base failure rate of a contactor (per million operations)", "5-9",
                         table=table("load", {"ac_resistive": 1.10, "ac_inductive": 3.60, "dc": 2.5})),
                    [
                        factor("C_V", "Voltage", "5-11", expr="V_ratio ** 0.75 if load != 'dc' else V_ratio ** 1.33",
                               source="Figures 5.3 (AC) and 5.6 (DC)", words="more voltage for its rating"),
                        factor("C_I", "Current", "5-12",
                               expr="3.50 * I_ratio ** 1.14 if load != 'dc' else 4.20 * I_ratio ** 1.30",
                               source="Figures 5.4 (AC) and 5.7 (DC)", words="more current for its rating"),
                        factor("C_PF", "Power factor", "5-13", expr="4.0 * PF ** 2", source="Figure 5.5",
                               when="load == 'ac_inductive'", words="a higher power factor (as printed)"),
                    ], symbol="λ_C")],
        rate_unit="per_million_operations",
        notes="Failure is taken as the contact resistance reaching about twice its initial value (p. 5-8).",
        failure_modes=_CONTACTOR_MODES,
    ),
]
