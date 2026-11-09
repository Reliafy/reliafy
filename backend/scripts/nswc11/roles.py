"""What each NSWC-11 input is (Derryn, 9 Nov 2026): a covariate is fixed by the **design**
(material, geometry, finish, type, how many, a catalogue rating), set by how it's **use**d (load,
speed, pressure, duty, cycles) or by the **environment** it works in (temperature, contamination,
humidity, vibration, supply quality). A position may fix some, all or none; use and environment
can be set per block (or for the whole diagram) in an RBD.

One table, reviewed in one place, rather than a word on every input in the chapters. The build
fails on an input with no role here. Judgement calls: a rated or allowable value (a load rating, an
allowable leakage, a rated temperature) is design; the fluid handled and the lubricant actually
used are use; filtration and supply-voltage quality are environment.
"""

ROLES: dict[str, dict[str, str]] = {
    'seal-static': {
        'shape': 'design',  # Seal shape
        'P1': 'use',  # System (upstream) pressure
        'P2': 'use',  # Downstream pressure (atmospheric if it leaks to air)
        'Q_f': 'design',  # Allowable leakage
        'D_SL': 'design',  # Inner diameter of the seal (circular seals)
        'L': 'design',  # Total linear length of the gasket (gaskets)
        'w': 'design',  # Minimum width of the gasket (gaskets)
        'M': 'design',  # Meyer hardness of the softer material (Young's modulus for rubber)
        'C': 'design',  # Contact stress at the seal
        'f': 'design',  # Surface finish of the seat (the harder surface)
        'T_R': 'design',  # Maximum rated temperature of the seal material
        'T_O': 'environment',  # Operating temperature (of the fluid at the seal)
        'fluid': 'use',  # Fluid sealed
        'nu_cP': 'environment',  # Dynamic viscosity of the fluid at its operating temperature (another fluid only)
        'source': 'environment',  # Upstream component producing contaminants
        'C_o': 'environment',  # System filter size
        'FR': 'design',  # Rated flow rate
    },
    'seal-dynamic': {
        'P1': 'use',  # System (upstream) pressure
        'P2': 'use',  # Downstream pressure (atmospheric if it leaks to air)
        'Q_f': 'design',  # Allowable leakage
        'D_SL': 'design',  # Seal diameter (inner)
        'n': 'use',  # Shaft speed (rotating seals)
        'V_lin': 'use',  # Sliding speed (reciprocating seals)
        'M': 'design',  # Meyer hardness of the softer material (Young's modulus for rubber)
        'C': 'design',  # Contact stress at the seal
        'f': 'design',  # Surface finish of the surface the seal runs on
        'T_R': 'design',  # Maximum rated temperature of the seal material
        'T_O': 'environment',  # Operating temperature (of the fluid at the seal)
        'fluid': 'use',  # Fluid sealed
        'nu_cP': 'environment',  # Dynamic viscosity of the fluid at its operating temperature (another fluid only)
        'source': 'environment',  # Upstream component producing contaminants
        'C_o': 'environment',  # System filter size
        'FR': 'design',  # Rated flow rate
        'balance': 'design',  # Seal balance
        'PV_DS': 'design',  # Design PV of the seal (from its maker; fast seals)
    },
    'seal-mechanical': {
        'P1': 'use',  # System (upstream) pressure
        'P2': 'use',  # Downstream pressure (atmospheric if it leaks to air)
        'Q_f': 'design',  # Allowable leakage
        'd': 'design',  # Seal diameter
        'n': 'use',  # Shaft speed
        'f': 'design',  # Surface finish of the seal faces
        'T_R': 'design',  # Maximum rated temperature of the seal material
        'T_O': 'environment',  # Operating temperature (of the fluid at the seal)
        'fluid': 'use',  # Fluid sealed
        'nu_cP': 'environment',  # Dynamic viscosity of the fluid at its operating temperature (another fluid only)
        'source': 'environment',  # Upstream component producing contaminants
        'C_o': 'environment',  # System filter size
        'FR': 'design',  # Rated flow rate
        'balance': 'design',  # Seal balance
        'PV_DS': 'design',  # Design PV of the seal faces (from the maker)
    },
    'spring-compression': {
        'G_M': 'design',  # Modulus of rigidity of the spring material
        'D_W': 'design',  # Wire diameter
        'D_C': 'design',  # Mean coil diameter
        'N_a': 'design',  # Number of active coils
        'T_S': 'design',  # Tensile strength of the spring material
        'L1': 'use',  # Spring length at the start of the stroke
        'L2': 'use',  # Spring length at the end of the stroke
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'spring-extension': {
        'G_M': 'design',  # Modulus of rigidity of the spring material
        'D_W': 'design',  # Wire diameter
        'D_C': 'design',  # Mean coil diameter
        'N_a': 'design',  # Number of active coils
        'T_S': 'design',  # Tensile strength of the spring material
        'L1': 'use',  # Spring length at the start of the stroke
        'L2': 'use',  # Spring length at the end of the stroke
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'spring-torsion': {
        'E_M': 'design',  # Modulus of elasticity of the spring material
        'D_W': 'design',  # Wire diameter
        'D_C': 'design',  # Mean coil diameter
        'N_a': 'design',  # Number of active coils
        'T_S': 'design',  # Tensile strength of the spring material
        'theta': 'use',  # Angular deflection from the free position
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'spring-curved-washer': {
        'E_M': 'design',  # Modulus of elasticity of the spring material
        't': 'design',  # Material thickness
        'OD': 'design',  # Outside diameter of the washer
        'f': 'use',  # Washer deflection
        'T_S': 'design',  # Tensile strength of the spring material
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'spring-wave-washer': {
        'E_M': 'design',  # Modulus of elasticity of the spring material
        't': 'design',  # Material thickness
        'OD': 'design',  # Outside diameter of the washer
        'f': 'use',  # Washer deflection
        'N': 'design',  # Number of waves
        'T_S': 'design',  # Tensile strength of the spring material
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'spring-belleville': {
        'E_M': 'design',  # Modulus of elasticity of the spring material
        't': 'design',  # Material thickness
        'OD': 'design',  # Outside diameter of the washer
        'f': 'use',  # Washer deflection
        'ID': 'design',  # Inside diameter of the washer
        'T_S': 'design',  # Tensile strength of the spring material
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'spring-cantilever': {
        'E_M': 'design',  # Modulus of elasticity of the spring material
        't': 'design',  # Material thickness
        'L': 'design',  # Active length of the spring
        'f': 'use',  # Spring deflection
        'T_S': 'design',  # Tensile strength of the spring material
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'spring-beam': {
        'E_M': 'design',  # Modulus of elasticity of the spring material
        't': 'design',  # Material thickness
        'L': 'design',  # Active length of the spring
        'f': 'use',  # Spring deflection
        'T_S': 'design',  # Tensile strength of the spring material
        'cycle_rate': 'use',  # Spring cycle rate
        'C_R': 'environment',  # Corrosion factor (from experience)
        'C_M': 'design',  # Manufacturing quality factor (from experience)
    },
    'solenoid': {
        'T_R': 'design',  # Rated temperature of the solenoid (its insulation class)
        'T_O': 'environment',  # Operating temperature of the solenoid coil
        'environment': 'environment',  # Operating environment
        'duty': 'use',  # Load and stroke
        'ops_per_min': 'use',  # Use rate
    },
    'contactor': {
        'load': 'use',  # Load type
        'V_o': 'use',  # Operating voltage
        'V_r': 'design',  # Rated voltage
        'I_o': 'use',  # Operating current
        'I_r': 'design',  # Rated current
        'PF': 'use',  # Power factor (AC inductive loads)
    },
    'valve-poppet': {
        'P1': 'use',  # Upstream pressure
        'P2': 'use',  # Downstream pressure
        'Q_f': 'design',  # Leakage that counts as a valve failure
        'f': 'design',  # Mean surface finish of the poppet and seat
        'S_S': 'design',  # Contact pressure of the poppet on its seat
        'D_S': 'design',  # Seat diameter (mean)
        'L_W': 'design',  # Radial seat land width
        'T_O': 'environment',  # Fluid temperature
        'fluid': 'use',  # Fluid
        'nu_cP': 'environment',  # Dynamic viscosity of the fluid at its temperature (another fluid only)
        'source': 'environment',  # Upstream component producing contaminants
        'C_o': 'environment',  # System filter size
        'FR': 'design',  # Rated flow rate
        'F_L': 'use',  # Actual flow rate ÷ the maker's rated flow
    },
    'valve-sliding': {
        'P1': 'use',  # Upstream pressure
        'P2': 'use',  # Downstream pressure
        'Q_f': 'design',  # Leakage that counts as a valve failure
        'B': 'design',  # Diametrical spool-to-sleeve clearance
        'D_SP': 'design',  # Spool diameter
        'mu': 'design',  # Static friction coefficient, spool on sleeve
        'T_O': 'environment',  # Fluid temperature
        'fluid': 'use',  # Fluid
        'nu_cP': 'environment',  # Dynamic viscosity of the fluid at its temperature (another fluid only)
        'source': 'environment',  # Upstream component producing contaminants
        'C_o': 'environment',  # System filter size
        'FR': 'design',  # Rated flow rate
        'F_L': 'use',  # Actual flow rate ÷ the maker's rated flow
    },
    'valve-housing': {
    },
    'valve-assembly': {
        'n_seals': 'design',  # Number of seals
        'n_springs': 'design',  # Number of springs
        'n_solenoids': 'design',  # Number of solenoids
    },
    'valve-assembly-sliding': {
        'n_seals': 'design',  # Number of seals
        'n_springs': 'design',  # Number of springs
        'n_solenoids': 'design',  # Number of solenoids
    },
    'bearing-rolling-load-rating': {
        'L_S': 'design',  # Dynamic load rating (catalogue)
        'F_R': 'use',  # Radial load
        'F_A': 'use',  # Axial (thrust) load
        'X': 'design',  # Radial factor (catalogue)
        'Y': 'design',  # Thrust factor (catalogue)
        'n': 'use',  # Operating speed
        'R': 'design',  # Reliability the life is quoted at
        'nu_ratio': 'use',  # Viscosity of the specified lubricant ÷ viscosity of the one used
        'CW': 'environment',  # Water in the lubricant
        'T_O': 'environment',  # Bearing operating temperature
        'bearing_type': 'design',  # Bearing type
        'service': 'use',  # Type of application (service factor)
        'contamination': 'environment',  # Lubricant cleanliness
        'diameter': 'design',  # Bearing diameter
    },
    'bearing-rolling-known-l10': {
        'L10h': 'design',  # Rated L10 life
        'L_A': 'use',  # Equivalent radial load in service
        'L_S': 'design',  # Dynamic load rating (catalogue)
        'R': 'design',  # Reliability the life is quoted at
        'nu_ratio': 'use',  # Viscosity of the specified lubricant ÷ viscosity of the one used
        'CW': 'environment',  # Water in the lubricant
        'T_O': 'environment',  # Bearing operating temperature
        'bearing_type': 'design',  # Bearing type
        'service': 'use',  # Type of application (service factor)
        'contamination': 'environment',  # Lubricant cleanliness
        'diameter': 'design',  # Bearing diameter
    },
    'gear': {
        'V_o': 'use',  # Operating speed
        'V_d': 'design',  # Design speed
        'L_O': 'use',  # Operating load
        'L_D': 'design',  # Design load
        'A_E': 'use',  # Misalignment angle
        'nu_ratio': 'use',  # Viscosity of the specified lubricant ÷ viscosity of the one used
        'T_AT': 'environment',  # Operating temperature
        'prime_mover': 'use',  # Prime mover
        'driven_load': 'use',  # Character of the load on the driven member
        'life_rev': 'design',  # Design life
    },
    'gear-known-rate': {
        'lambda_GB': 'design',  # Base failure rate at the design conditions
        'V_o': 'use',  # Operating speed
        'V_d': 'design',  # Design speed
        'L_O': 'use',  # Operating load
        'L_D': 'design',  # Design load
        'A_E': 'use',  # Misalignment angle
        'nu_ratio': 'use',  # Viscosity of the specified lubricant ÷ viscosity of the one used
        'T_AT': 'environment',  # Operating temperature
        'prime_mover': 'use',  # Prime mover
        'driven_load': 'use',  # Character of the load on the driven member
    },
    'spline': {
        'G_L': 'design',  # Spline length
        'G_D': 'design',  # Spline diameter
        'G_T': 'use',  # Torque
        'G_B': 'design',  # Tooth hardness (Brinell hardness number)
        'A_E': 'use',  # Misalignment angle
        'V_o': 'use',  # Operating speed
        'V_d': 'design',  # Design speed
        'nu_ratio': 'use',  # Viscosity of the specified lubricant ÷ viscosity of the one used
        'T_AT': 'environment',  # Operating temperature
        'prime_mover': 'use',  # Prime mover
        'driven_load': 'use',  # Character of the load on the driven member
    },
    'actuator-side-load': {
        'W_S': 'use',  # Side load on the actuator
        'L': 'design',  # Total contact length between piston and cylinder
        'D1': 'design',  # Cylinder bore diameter
        'D2': 'design',  # Piston diameter
        'eta1': 'design',  # Poisson's ratio, cylinder
        'eta2': 'design',  # Poisson's ratio, piston
        'E1': 'design',  # Modulus of elasticity, cylinder
        'E2': 'design',  # Modulus of elasticity, piston
        'F_Y': 'design',  # Yield strength of the softer material
        'wear': 'design',  # Wear behaviour of the materials (wear factor γ)
        'C_H': 'environment',  # Hardest particle's hardness ÷ piston hardness
        'filter_micron': 'environment',  # Filter rating
        'C_N': 'environment',  # Particle size and number factor
        'T_O': 'environment',  # Operating temperature
        'theta': 'design',  # Activation energy constant
    },
    'actuator-axial-load': {
        'W_A': 'use',  # Axial load on the actuator
        'D1': 'design',  # Cylinder bore diameter
        'D2': 'design',  # Piston diameter
        'eta1': 'design',  # Poisson's ratio, cylinder
        'eta2': 'design',  # Poisson's ratio, piston
        'E1': 'design',  # Modulus of elasticity, cylinder
        'E2': 'design',  # Modulus of elasticity, piston
        'F_Y': 'design',  # Yield strength of the softer material
        'wear': 'design',  # Wear behaviour of the materials (wear factor γ)
        'C_H': 'environment',  # Hardest particle's hardness ÷ piston hardness
        'filter_micron': 'environment',  # Filter rating
        'C_N': 'environment',  # Particle size and number factor
        'T_O': 'environment',  # Operating temperature
        'theta': 'design',  # Activation energy constant
    },
    'pump-fluid-driver': {
        'driver': 'design',  # Fluid driver (Table 10-4)
        'casing': 'design',  # Casing (for the flow factor)
        'Q': 'use',  # Actual operating flow
        'Q_r': 'design',  # Maximum specified pump flow
        'V_O': 'use',  # Operating speed
        'V_D': 'design',  # Maximum allowable design speed
        'F_AC': 'environment',  # Filter size
        'duty': 'use',  # Duration of service
        'load': 'use',  # Load
    },
    'pump': {
        'n_SE': 'design',  # Number of mechanical seals
        'n_BE': 'design',  # Number of bearings
    },
    'filter-fluid': {
        'lambda_FB': 'design',  # Base failure rate (2.53, or 10⁶ ÷ the maker's life in hours)
        'P_O': 'use',  # Operating pressure upstream of the filter
        'P_R': 'use',  # Rated filter pressure
        'mobile': 'environment',  # System type (vibration)
        'nu_ratio': 'environment',  # Viscosity at a cold start ÷ viscosity at normal operation
        'fluid': 'use',  # Fluid (sets the cold-start exponent x)
        'pore': 'design',  # Filter medium
        'surge': 'use',  # Flow surge frequency
    },
    'brake-friction-material': {
        'material': 'design',  # Lining (pad) material (wear coefficient)
        'P': 'use',  # Applied load
        'v_s': 'use',  # Sliding velocity
        't_b': 'use',  # Braking time per application
        'd': 'design',  # Lining thickness (effective)
        'A': 'design',  # Brake lining area
        'n_per_hour': 'use',  # Brake applications per hour
        'brake_type': 'design',  # Brake type
        'dust': 'environment',  # Dust
        'binder': 'design',  # Binder resin of the friction material
        'lining_type': 'design',  # Lining type (for the temperature factor)
        'T': 'environment',  # Ambient temperature
    },
    'brake-friction-material-known-rate': {
        'lambda_B': 'design',  # Base failure rate from the maker
        'brake_type': 'design',  # Brake type
        'dust': 'environment',  # Dust
        'binder': 'design',  # Binder resin of the friction material
        'lining_type': 'design',  # Lining type (for the temperature factor)
        'T': 'environment',  # Ambient temperature
    },
    'clutch-friction-material': {
        'material': 'design',  # Lining (pad) material (wear coefficient)
        'P': 'use',  # Applied load
        'v_s': 'use',  # Sliding velocity
        't_a': 'use',  # Clutch actuation (slip) time per engagement
        'd': 'design',  # Lining thickness (effective)
        'A': 'design',  # Clutch lining area
        'n_per_hour': 'use',  # Clutch applications per hour
        'N_P': 'design',  # Number of disks in the clutch
        'lining_type': 'design',  # Lining type (for the temperature factor)
        'T': 'environment',  # Ambient temperature
    },
    'clutch-friction-material-known-rate': {
        'lambda_B': 'design',  # Base failure rate from the maker
        'N_P': 'design',  # Number of disks in the clutch
        'lining_type': 'design',  # Lining type (for the temperature factor)
        'T': 'environment',  # Ambient temperature
    },
    'brake-assembly': {
        'AC_cycles_per_hour': 'use',  # Actuator cycles per hour (all actuators together)
        'n_SP': 'design',  # Number of springs
        'n_BE': 'design',  # Number of bearings
        'n_SE': 'design',  # Number of seals
    },
    'clutch-assembly': {
        'AC_cycles_per_hour': 'use',  # Actuator cycles per hour (all actuators together)
        'n_SP': 'design',  # Number of springs
        'n_BE': 'design',  # Number of bearings
        'n_SE': 'design',  # Number of seals
    },
    'compressor': {
        'driver': 'design',  # Fluid driver (compressor type)
        'high_duty': 'use',  # High duty cycle (more than 5 cycles an hour)
        'extreme_temperature': 'environment',  # Extreme operating temperatures
        'unscheduled_lubrication': 'use',  # Non-scheduled lubrication checks
        'vibration_shock': 'environment',  # High vibration and/or heavy shock loading
        'poor_inlet_air': 'environment',  # Poor inlet air quality
        'n_BE': 'design',  # Number of shaft bearings
        'VA_ops_per_hour': 'use',  # Control valve operations per hour (all valves together)
        'n_SE': 'design',  # Number of seals
        'SH_cycles_per_hour': 'use',  # Shaft cycles per hour
    },
    'compressor-diaphragm': {
        'F': 'use',  # Force on the diaphragm's rigid centre
        'a': 'design',  # Diaphragm radius
        'b': 'design',  # Radius of the rigid centre plate
        'h': 'design',  # Diaphragm thickness
        'IRHD': 'design',  # Rubber hardness (sets Young's modulus)
        'eta': 'design',  # Poisson's ratio
        'ozone': 'environment',  # Ozone in the air
        'coating': 'design',  # Anti-ozonant coating
        'C_LC': 'environment',  # Liquid contaminant factor (read from Figure 13.5)
        'T': 'environment',  # Temperature
    },
    'electric-motor': {
        'motor_type': 'design',  # Type of motor
        'load': 'use',  # Type of load (service factor)
        'L_I': 'design',  # Expected winding life (maker's figure)
        'T_O': 'environment',  # Ambient temperature around the running motor at full load
        'VD_VR': 'environment',  # Supply voltage difference ÷ rated voltage
        'V_U': 'environment',  # Phase voltage unbalance
        'a': 'environment',  # Operating altitude
        'n_BS': 'design',  # Number of brushes
        'n_BE': 'design',  # Number of rolling bearings
        'lambda_C': 'design',  # Capacitor failure rate (from MIL-HDBK-217), if it has one
    },
    'electric-motor-geared': {
        'motor_type': 'design',  # Type of motor
        'load': 'use',  # Type of load (service factor)
        'L_I': 'design',  # Expected winding life (maker's figure)
        'T_O': 'environment',  # Ambient temperature around the running motor at full load
        'VD_VR': 'environment',  # Supply voltage difference ÷ rated voltage
        'V_U': 'environment',  # Phase voltage unbalance
        'a': 'environment',  # Operating altitude
        'n_BS': 'design',  # Number of brushes
        'n_BE': 'design',  # Number of rolling bearings
        'lambda_C': 'design',  # Capacitor failure rate (from MIL-HDBK-217), if it has one
        'n_GR': 'design',  # Number of gears
    },
    'electric-motor-winding': {
        'supply': 'design',  # Supply
        'L_I': 'design',  # Expected winding life (maker's figure)
        'T_O': 'environment',  # Ambient temperature around the running motor at full load
        'VD_VR': 'environment',  # Supply voltage difference ÷ rated voltage
        'V_U': 'environment',  # Phase voltage unbalance
        'a': 'environment',  # Operating altitude
    },
    'accumulator-cylinder-wall': {
        'P': 'use',  # Internal pressure (mean)
        's_P': 'use',  # Standard deviation of the internal pressure
        'r_i': 'design',  # Internal radius
        't': 'design',  # Wall thickness
        'joint_c': 'design',  # Joint efficiency for the circumferential stress (longitudinal seam)
        'joint_l': 'design',  # Joint efficiency for the longitudinal stress (circumferential seam)
        'F_y': 'design',  # Material yield strength (mean)
        's_Fy': 'design',  # Standard deviation of the yield strength
        't_op': 'use',  # Period the reliability applies over
    },
    'accumulator-spring-loaded': {
        'n_SE': 'design',  # Number of piston seals
        'n_SP': 'design',  # Number of springs
    },
    'accumulator-gas-charged': {
        'n_SE': 'design',  # Number of piston seals
    },
    'fastener': {
        'grade': 'design',  # Grade or class, and diameter
        'load': 'use',  # Type of load applied
        'T_O': 'environment',  # Fastener operating temperature
        'impact': 'use',  # Impact category (the machine the joint is on)
        'vibration': 'environment',  # Vibration
        'thread_band': 'design',  # Bolt strength band for the thread factor
        'thread_form': 'design',  # How the threads were made
    },
    'fastener-test-data': {
        'lambda_FB': 'design',  # Base failure rate from the fastener's test data
        'd': 'design',  # Major diameter of the fastener
        'load': 'use',  # Type of load applied
        'T_O': 'environment',  # Fastener operating temperature
        'impact': 'use',  # Impact category (the machine the joint is on)
        'vibration': 'environment',  # Vibration
        'thread_band': 'design',  # Bolt strength band for the thread factor
        'thread_form': 'design',  # How the threads were made
    },
    'coupling-endurance': {
        'N_cycles': 'design',  # Cycles to failure at the working stress
        'driven': 'use',  # Driven machinery
        'torque': 'use',  # Torque characteristic
    },
    'coupling-gear': {
        'lambda_CP_B': 'design',  # Base failure rate of the coupling
        'driven': 'use',  # Driven machinery
        'torque': 'use',  # Torque characteristic
        'n_GR': 'design',  # Number of gear meshes
        'n_SE': 'design',  # Number of seals
    },
    'coupling-universal-joint': {
        'n_BE': 'design',  # Number of bearings
        'n_SE': 'design',  # Number of seals
        'n_F': 'design',  # Number of fasteners
    },
    'slider-crank': {
        'n_BE': 'design',  # Number of rolling bearings
        'n_RD': 'design',  # Number of rods or links
        'n_SE': 'design',  # Number of static seals and gaskets
        'n_RI': 'design',  # Number of rings and dynamic seals
    },
    'sensor': {
        'element': 'design',  # Sensing element
        'lam_TDB': 'design',  # Base failure rate of the sensor
        'lam_T': 'design',  # Transmission line
        'lam_C': 'design',  # Computational device
        'lam_P': 'design',  # Power source
        'lam_X': 'design',  # Other parts of the sensor or network
    },
    'shaft': {
        'N_cycles': 'design',  # Cycles to failure at the application stress
        'finish': 'design',  # Surface finish
        'T_S': 'design',  # Tensile strength of the material
        'T_AT': 'environment',  # Operating temperature
        'F': 'use',  # Radial unbalance force or load weight
        'E': 'design',  # Modulus of elasticity of the shaft material
        'b': 'design',  # Allowable shaft deflection
        'len_X': 'design',  # Length of shaft section X
        'D_X': 'design',  # Diameter of shaft section X
        'len_L': 'design',  # Length of shaft section L
        'D_L': 'design',  # Diameter of shaft section L
        'len_M': 'design',  # Length of shaft section M
        'D_M': 'design',  # Diameter of shaft section M
        'len_N': 'design',  # Length of shaft section N
        'D_N': 'design',  # Diameter of shaft section N
        'r': 'design',  # Fillet radius at the shoulder
        'D_big': 'design',  # Shaft diameter before the shoulder
        'd_small': 'design',  # Shaft diameter after the shoulder
        'groove': 'design',  # Shaft grooves (Table 20-4)
    },
    'belt-drive': {
        'hp_O': 'use',  # Power the belt transmits in service
        'hp_D': 'design',  # Belt's rated (design) power
        'T_O': 'environment',  # Belt operating temperature
        'PD': 'design',  # Driven pulley pitch diameter
        'belt_type': 'design',  # Belt section
        'torque': 'use',  # Driver (source of power)
        'service': 'use',  # Hours of service
        'driven_load': 'use',  # Driven load
        'shock': 'use',  # Shock from the driven machinery
        'pulley_type': 'design',  # Pulleys
    },
    'chain-drive': {
        'P': 'design',  # Chain pitch
        'n': 'use',  # Speed of the smaller sprocket
        'ST': 'design',  # Teeth on the smaller sprocket
        'T_C': 'environment',  # Chain operating temperature
        'driver': 'use',  # Driver sprocket's power source
        'load': 'use',  # Type of driven load
        'lubrication': 'design',  # Lubrication
    },
    'pipe-assembly': {
        'n_conn': 'design',  # Number of connections
        'environment': 'environment',  # Operating environment
    },
    'tubing-assembly': {
        'n_conn': 'design',  # Number of connections
        'environment': 'environment',  # Operating environment
    },
    'hose-assembly': {
        'T_R': 'environment',  # Hose's rated temperature
        'T_O': 'environment',  # Hose's operating temperature
        'environment': 'environment',  # Operating environment
    },
    'axle': {
    },
    'bolt': {
        'loading': 'use',  # Loading
        'vibration': 'environment',  # Vibration
        'n_bolts': 'design',  # Number of bolts
    },
    'bushing': {
    },
    'cam-mechanism': {
    },
    'fitting': {
        'fitting_type': 'design',  # Fitting type
    },
    'flywheel': {
        'shock': 'use',  # Driven machinery
        'duty': 'use',  # Torque and velocity
    },
    'hinge': {
    },
    'key-pin': {
    },
    'pillow-block': {
    },
    'pillow-block-from-l10': {
    },
    'power-screw': {
        'lam_PSB': 'design',  # Failure rate from the screw's published life
        'L_A': 'use',  # Equivalent load in service
        'L_S': 'design',  # Basic dynamic load rating
    },
    'rivet': {
        'holes': 'design',  # Rivet holes
    },
    'setscrew': {
        'environment': 'environment',  # Operating environment
        'humidity': 'environment',  # Humidity
    },
    'wire-rope': {
    },
}
