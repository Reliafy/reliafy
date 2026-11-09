"""Chapter 19, Sensors and transducers (Revision B): the sensor network sum, Eq. 19-1.

Checked against the rendered pages 19-14, 19-16 and 19-17:
- Eq. 19-1 (p. 19-14): λ_TD = λ_TD,B + λ_S + λ_T + λ_C + λ_P + … + λ_X, all in failures
  per million hours. λ_S, the sensing element, is from Table 19-4 (pp. 19-16, 19-17);
  the transmission line λ_T, computational device λ_C and power source λ_P are from
  the electronic parts handbook the chapter cites (its Reference 28), so here they are
  numbers the user gives; λ_X is any other part (e.g. a spring from Chapter 4).
- Ambiguity: λ_TD,B, "base failure rate of sensor", has no value or procedure anywhere
  in the chapter, and λ_S already carries the sensing element's typical rate. The model
  keeps λ_TD,B as an input that defaults to 0 (nothing added) and says so.
- Table 19-4 prints no unit; Eq. 19-1's terms are failures per million hours, and the
  table's values are read in that unit. Rows that repeat across classes (semiconductor
  strain gauge 23.00, semiconductor infrared 7.50, photosensor 0.16) are kept in each
  class as printed. The thermocouple's rate excludes any amplifier, controller or power
  supply (the table's footnote).
- The handbook gives no multiplying factors for sensors: its Table 19-5 lists what to
  consider (battery, connectors, drift, temperature, shock …) in words only.
"""

from backend.scripts.nswc11.common import base, choice, mode, non_negative, num, record, table

#: Table 19-4: (code, class, sensor, technology, λ_S), in the handbook's order.
ELEMENTS = [
    ("thermal_rtd", "Thermal", "RTD", "resistive", 1.50),
    ("thermal_thermistor", "Thermal", "Thermistor", "semiconductor", 3.50),
    ("thermal_thermocouple", "Thermal", "Thermocouple", "thermoelectric", 5.00),
    ("thermal_infrared", "Thermal", "Infrared", "emissivity", 7.50),
    ("thermal_thermostat", "Thermal", "Thermostat", "bimetallic", 20.00),
    ("force_transducer", "Mechanical force/pressure", "Force transducer", "semiconductor", 4.00),
    ("force_strain_gauge_resistive", "Mechanical force/pressure", "Strain gauge", "resistive", 7.50),
    ("force_strain_gauge_semiconductor", "Mechanical force/pressure", "Strain gauge", "semiconductor", 23.00),
    ("force_torque_transducer", "Mechanical force/pressure", "Torque transducer", "magnetic", 4.50),
    ("force_load_cell", "Mechanical force/pressure", "Load cell", "strain gauge", 23.00),
    ("fluid_pressure", "Fluid", "Fluid pressure sensor", "piezoelectric", 13.00),
    ("fluid_flow", "Fluid", "Fluid flow sensor", "resistive", 14.30),
    ("fluid_level", "Fluid", "Fluid level sensor", "capacitance", 10.70),
    ("fluid_air_flow", "Fluid", "Air flow sensor", "vane meter", 8.50),
    ("optical_photodiode", "Optical", "Photodiode", "semiconductor", 0.16),
    ("optical_phototransistor", "Optical", "Phototransistor", "semiconductor", 0.65),
    ("optical_photodetector", "Optical", "Photodetector", "semiconductor", 0.03),
    ("optical_infrared", "Optical", "Infrared sensor", "semiconductor", 7.50),
    ("optical_solar_cell", "Optical", "Solar cell", "photovoltaic", 1.00),
    ("position_analog_pot", "Position", "Analogue potentiometer", "resistive", 1.50),
    ("position_digital_pot", "Position", "Digital potentiometer", "semiconductor", 2.50),
    ("position_lvdt", "Position", "LVDT", "transformer", 7.50),
    ("position_encoder_optical", "Position", "Rotary encoder", "optical", 8.00),
    ("position_encoder_magnetic", "Position", "Rotary encoder", "magnetic", 5.00),
    ("motion_linear_displacement", "Motion", "Linear displacement", "resistive", 2.50),
    ("motion_rotary_displacement", "Motion", "Rotary displacement", "resistive", 3.50),
    ("motion_displacement_capacitive", "Motion", "Displacement sensor", "capacitive", 10.70),
    ("motion_displacement_inductive", "Motion", "Displacement sensor", "inductive", 8.50),
    ("motion_velocity_hall", "Motion", "Velocity sensor", "Hall effect", 2.50),
    ("motion_velocity_em", "Motion", "Velocity sensor", "electromagnetic", 3.50),
    ("motion_velocity_rotational", "Motion", "Velocity sensor", "rotational", 2.50),
    ("motion_optical_photosensor", "Motion", "Optical photosensor", "semiconductor", 0.16),
    ("motion_optical_infrared", "Motion", "Optical infrared", "semiconductor", 7.50),
    ("presence_proximity", "Presence, proximity", "Proximity sensor", "electromagnetic", 15.38),
    ("presence_infrared", "Presence, proximity", "Infrared", "semiconductor", 7.50),
    ("env_altitude", "Environmental", "Altitude sensor", "piezoelectric", 3.39),
    ("env_humidity_resistive", "Environmental", "Humidity sensor", "resistive", 20.44),
    ("env_humidity_capacitive", "Environmental", "Humidity sensor", "capacitive", 20.44),
    ("env_accelerometer_piezoresistive", "Environmental", "Accelerometer", "piezoresistive", 15.00),
    ("env_accelerometer_piezoelectric", "Environmental", "Accelerometer", "piezoelectric", 13.00),
    ("env_strain_gauge_semiconductor", "Environmental", "Strain gauge", "semiconductor", 23.00),
    ("env_smoke_ionisation", "Environmental", "Smoke detector", "ionisation", 8.00),
    ("env_smoke_photoelectric", "Environmental", "Smoke detector", "photoelectric", 6.50),
]

_FAILURE_MODES = [
    "Incorrect signal from the sensing element (low signal, impedance mismatch, A/D error)",
    "Loss of signal from the sensing element (chip failure, corrosion)",
    "Loss of signal in the transmission line (broken wire, fibre or RF interruption)",
    "Signal error in the transmission line (power line interference, contaminants)",
    "Incorrect signal from the computing device (algorithm error)",
    "Power supply loses voltage",
    "Improper response to the information (misinterpretation, malfunction)",
    "Calibration error (software or algorithm)",
    "Battery runs flat",
]


def _rate(name: str, label: str, symbol: str, help: str) -> dict:
    return num(name, label, "failures per million hours", [non_negative("a failure rate can't be negative")],
               default=0, default_basis="neutral", symbol=symbol, page="19-14", help=help)


def _part(key: str, name: str, symbol: str, inp: str) -> dict:
    return mode(key, name, base(symbol, name, "19-14", expr=inp, equation="19-1"), symbol=symbol)


RECORDS = [
    record(
        "sensor", "Sensor or transducer (sensing element and its network)", "sensor", 19,
        "19.4 Sensor failure rate model development", "19-1", "19-14",
        "λ_TD = λ_TD,B + λ_S + λ_T + λ_C + λ_P + … + λ_X",
        "A sensor's failure rate is the sum of its parts: the sensing element's typical rate from the handbook's "
        "table, plus whatever it's wired to (the transmission line, the computing device, the power source and any "
        "other part), each rated on its own.",
        inputs=[
            choice("element", "Sensing element", [(c, f"{cls}: {s} ({tech})") for c, cls, s, tech, _ in ELEMENTS],
                   symbol="λ_S", page="19-16"),
            _rate("lam_TDB", "Base failure rate of the sensor", "λ_TD,B",
                  "The handbook names this term but gives no value for it: 0 adds nothing beyond the sensing element."),
            _rate("lam_T", "Transmission line", "λ_T", "From an electronic parts prediction; 0 when there is none."),
            _rate("lam_C", "Computational device", "λ_C", "From an electronic parts prediction; 0 when there is none."),
            _rate("lam_P", "Power source", "λ_P", "From an electronic parts prediction; 0 when there is none."),
            _rate("lam_X", "Other parts of the sensor or network", "λ_X",
                  "Any other part, e.g. a spring (Chapter 4) or a transformer; 0 when there is none."),
        ],
        modes=[
            _part("base", "Base failure rate of the sensor", "λ_TD,B", "lam_TDB"),
            mode("element", "Sensing element",
                 base("λ_S", "Typical failure rate of the sensing element", "19-16",
                      table=table("element", {c: v for c, _, _, _, v in ELEMENTS}), source="Table 19-4",
                      equation="19-1"), symbol="λ_S"),
            _part("line", "Transmission line", "λ_T", "lam_T"),
            _part("computer", "Computational device", "λ_C", "lam_C"),
            _part("power", "Power source", "λ_P", "lam_P"),
            _part("other", "Other parts", "λ_X", "lam_X"),
        ],
        failure_modes=_FAILURE_MODES,
        notes=("Table 19-4's rates are typical commercial values with no conditions attached; the handbook asks "
               "that they be adjusted from experience with similar applications. It gives λ_TD,B no value, so it "
               "defaults to 0."),
    ),
]
