# Complete HPA Wing Pipeline v2

## Purpose

This document rewrites the wing design pipeline as one coherent data flow:

```text
Mission contract
-> Fourier-AVL calibration
-> Fourier spanload candidate generation
-> smooth production geometry realization
-> AVL realization check
-> structure-budgeted loaded-Z search
-> AVL recheck on realizable loaded shape
-> Tier2 full-alpha airfoil selection
-> aero-structure closure
-> final verification
```

This is a specification and implementation plan only. It must not run
optimization, change production ranking, add hard gates, rerun CST/NSGA, or
promote any current structural result to final truth.

## Core Philosophy

Do not optimize airfoils first and only later ask whether the structure can
realize the wing.

The correct order is:

```text
Mission / mass budget
-> spanload design
-> Fourier-AVL calibration
-> geometry realization
-> AVL actual spanload
-> structure-budgeted loaded-shape search
-> AVL recheck on realizable loaded shape
-> Tier2 airfoil database selection
-> aero-structure closure
-> final verification
```

The reason is simple: airfoil selection depends on local Cl and Reynolds number,
but local Cl and Reynolds number depend on the actual AVL spanload, which changes
when the loaded shape and structural realization change.

## Stage 0: Mission Contract

Stage 0 defines the problem before any wing optimization.

### Mission

- Aircraft type: human-powered aircraft for Birdman-style mission.
- Target distance: `42.195 km`.
- Cruise speed target: approximately `6.5-6.7 m/s`.
- Objective: minimize crank power while staying manufacturable and structurally
  feasible.
- Current production-level aerodynamic candidates may be around `170-180 W`
  crank, but structure and loaded-shape closure are not final.

### Required Inputs

- `m_total_kg`: design total mass or design mass range.
- `rho_kg_m3`: air density.
- `V_mps`: cruise speed.
- `b_m`: span.
- `AR`: aspect ratio.
- `S_m2`: wing area.
- `eta_prop`: propeller efficiency.
- `eta_drive`: drivetrain efficiency.
- `CDA_nonwing_m2`: nonwing drag reserve.
- `target_range_km`: mission range.
- `tube_spar_mass_budget_kg`: full-span tube/spar mass budget.

### Basic Formulas

```text
S = b^2 / AR
q = 0.5 * rho * V^2
W = m_total * g
CL_req = W / (q * S)

CDi = CL_req^2 / (pi * AR * e)
CD0_total = CD_profile_wing + CDA_nonwing / S
CD_total = CD0_total + CDi
D = q * S * CD_total
P_aero = D * V
P_crank = P_aero / (eta_prop * eta_drive)
mission_time_s = target_range_m / V
mission_energy_J = P_crank * mission_time_s
```

### Structural Budget Contract

The current structural target should be treated as a budget, not a proven final
mass:

- tube/spar budget target: approximately `10.5-11.5 kg` class.
- old diagnostic line around `11.7534 kg` can be used as history, not truth.
- any `77 kg` result should be treated as a selector / clearance / recipe-grid
  artifact, not physical truth.
- mass basis must be explicit:
  - main spar tube only,
  - main + rear tubes,
  - full-span tube mass,
  - tube + wire + ribs,
  - total structural mass.

## Stage 1: Fourier-AVL Calibration Layer

Fourier should not be used as a trusted fast design tool until it has been
calibrated against AVL actual spanload.

This stage is not merely:

```text
Fourier target -> AVL -> compare
```

It must establish a bridge between the commanded Fourier language and the
realized AVL loading.

### 1. Define Common Spanload Representation

Every artifact must use the same convention:

- `y_m`: spanwise coordinate, root to tip on half wing.
- `eta`: normalized half-span coordinate, `eta = y / (b/2)`, root `0`, tip `1`.
- `theta`: lifting-line coordinate. One acceptable convention is
  `theta = acos(eta)`, so root is `pi/2` and tip is `0`. The chosen convention
  must be written into `spanload_definition.md`.
- `Lprime_Npm`: lift per unit span.
- `cl_times_c`: local section coefficient times chord, proportional to
  spanload.
- `Gamma_m2ps`: circulation proxy, approximately `Lprime / (rho * V)`.
- `normalized_loading`: spanload normalized so its half-span integral is one.
- half-span vs full-span convention: explicit in every CSV.

### 2. Fit AVL Actual Spanload Into Fourier Coefficients

For each AVL result:

```text
AVL actual spanload -> equivalent A1/A3/A5/A7
```

Fit odd low-order terms using least squares:

```text
Gamma(theta) ~= 2 * b * V * [A1 sin(theta)
                           + A3 sin(3 theta)
                           + A5 sin(5 theta)
                           + A7 sin(7 theta)]
```

Also store normalized ratios:

```text
r3 = A3 / A1
r5 = A5 / A1
r7 = A7 / A1
```

### 3. Compare Fourier Prediction Against AVL

For each candidate, compare:

- Fourier theoretical `e`.
- AVL `CDi` and `e_CDi`.
- Fourier bending proxy.
- AVL bending proxy from actual spanload.
- target-vs-AVL RMS mismatch.
- target-vs-AVL outer lift mismatch.

Fourier theoretical efficiency should use:

```text
e_fourier = 1 / (1 + 3*r3^2 + 5*r5^2 + 7*r7^2 + ...)
```

### 4. Build Commanded-Fourier To AVL-Realized Map

The bridge should answer:

```text
If I command r3/r5/r7, what r3/r5/r7 does AVL actually realize?
```

Start with a simple table:

```text
commanded_r3, commanded_r5, commanded_r7
realized_r3, realized_r5, realized_r7
delta_r3, delta_r5, delta_r7
target_vs_avl_rms
e_fourier_command
e_avl_realized
bending_proxy_command
bending_proxy_avl
```

Later, this can become an affine correction or a low-order response surface, but
the MVP should begin with explicit measured rows.

### 5. Diagnose Mismatch

Mismatch can come from:

- definition mismatch,
- half-span vs full-span factor,
- normalized loading mismatch,
- geometry realization issue,
- chord/twist authority issue,
- airfoil camber or alpha_L0 issue,
- loaded dihedral / nonplanar wing issue,
- AVL setup or reference-area issue.

The first calibration module should not hide mismatch. It should classify it.

### Stage 1 Outputs

- `spanload_definition.md`
- `avl_to_fourier_fit.csv`
- `fourier_command_to_avl_realized.csv`
- `fourier_avl_calibration_report.md`
- `recommended_fourier_bridge.md`

## Stage 2: Fourier Spanload Candidate Generator

After Stage 1, Fourier becomes a fast spanload design language, not a truth
source by itself.

Generate low-order families:

- current baseline,
- elliptical-like,
- more inboard-loaded,
- reduced outer loading,
- mildly outer-loaded,
- low-order `A3/A5` variants.

For each target, estimate:

- theoretical `e`,
- root bending proxy,
- outer lift fraction,
- local Cl risk,
- structural burden proxy,
- likely geometry authority risk.

This stage should be fast and broad, but still report uncertainty from the
Fourier-AVL bridge.

## Stage 3: Smooth Geometry Realization

Convert calibrated Fourier targets into production-like geometry.

Required geometry fields:

- span,
- area,
- AR,
- station `y`,
- smooth monotone chord,
- twist / incidence,
- provisional loaded `z`,
- placeholder airfoils or initial seed airfoils.

Production geometry rules:

- no faceted chord as production geometry,
- monotone or smoothly tapered chord preferred,
- chord slope and curvature must be reported,
- twist should be smooth and physically buildable,
- geometry must preserve the mission `S`, `b`, `AR`, and `CL_req` contract.

## Stage 4: AVL Realization Check

Run AVL on the realized geometry.

Required outputs:

- `CL_req`,
- `alpha_at_CL_req`,
- `CDi`,
- `e_CDi`,
- AVL actual spanload,
- local `Cl`,
- local Reynolds number,
- Fourier-vs-AVL mismatch,
- local Cl risk,
- root bending proxy from AVL.

Decision logic:

- if AVL setup is bad, fix AVL setup;
- if Fourier target is not realized, update geometry or Fourier correction;
- if AVL actual spanload is acceptable, candidate can proceed to structure;
- do not use this step to alter production ranking or add hard gates in the MVP.

## Stage 5: Structure-Budgeted Loaded-Z / Dihedral Search

This happens before final airfoil selection.

Inputs:

- AVL actual spanload from Stage 4,
- structural budget contract from Stage 0,
- canonical `direct_dual_beam_inverse_design` route,
- tube/spar mass target around `10.5-11.5 kg`,
- preferred total cruise effective dihedral around `6-7 deg`,
- jig clearance requirement,
- wire feasibility,
- jig feasibility.

### Required Z Definitions

Do not confuse these:

- `aero_surface_z`: aerodynamic surface station z.
- `main_beam_z`: main spar beam-line z.
- `rear_beam_z`: rear spar beam-line z.
- `built_in_geometric_z`: built-in geometric dihedral / pre-shape.
- `elastic_deflection_z`: load-induced structural deflection.
- `total_loaded_z`: built-in z plus elastic deflection in cruise.
- `total_cruise_effective_dihedral_deg`: total loaded shape relative to root or
  centerline, not extra elastic deflection only.

The `6-7 deg` target refers to total effective cruise dihedral, not merely
additional elastic deflection.

### Search Variables

Search loaded `z(y)`, not only scalar tip z:

- control-station loaded-shape families,
- spanload variants from Stage 2,
- wire attach / pretension / layout if available,
- tube recipe / spar mass budget class,
- smooth loaded-shape constraints.

### Stage 5 Outputs

- `z_state_structure_budget_sweep.csv`
- `feasible_loaded_shape_shortlist.csv`
- `z_definition_audit.md`
- `recommended_loaded_z_states.md`

## Stage 6: AVL Recheck On Realizable Loaded Shape

The loaded shape changes AVL spanload, so AVL must be rerun after structural
realization.

For each structurally plausible loaded shape:

- export realizable loaded shape,
- run AVL again,
- compute actual `CDi/e`,
- compute local `Cl/Re`,
- check stall margin,
- check spanload and bending proxy,
- compare with Stage 4.

This stage decides whether the structural loaded shape damaged the aerodynamic
intent.

## Stage 7: Tier2 Full-Alpha Airfoil Database Selection

Only run this after Stage 6.

Use the actual AVL `Cl/Re` envelope from structurally feasible loaded shapes.

Inputs:

- Tier2 full-alpha polar database,
- Stage 6 actual AVL `Cl/Re`,
- zone definitions: root / mid1 / mid2 / tip,
- candidate airfoil quality metadata,
- stall margin policy,
- roughness / archive quality policy.

Selection process:

- zone-level top-k selection,
- capped combo search,
- AVL `AFILE` rerun,
- profile drag integration using actual AVL local Cl,
- conservative vs raw comparison if needed.

Outputs:

- best aero airfoil assignment,
- best production-quality airfoil assignment,
- `profile_cd`,
- `CD0_total`,
- `P_crank`,
- `P_crank_conservative`,
- stall margin,
- actual-query quality,
- archive quality.

Do not run broad airfoil NSGA in this MVP. The Tier2 database exists to select
from usable full-alpha evidence after the structural loaded shape is known.

## Stage 8: Aero-Structure Closure

After airfoil selection:

- rerun AVL with selected airfoils,
- recompute spanload,
- recompute structure response,
- check loaded shape,
- check mass,
- check clearance,
- check wire,
- check jig feasibility.

Allow small mismatch tolerance, such as `1-5%`, for screening-level closure.

If mismatch is too large, loop back:

- to Stage 2/3 if the spanload or geometry target is wrong;
- to Stage 5 if the loaded-Z structural budget is wrong;
- to Stage 7 if airfoil selection materially changed local loading.

## Stage 9: Structural Model Calibration / Trust Layer

Use the dual-beam / tubing model for daily screening, but keep a validation
ladder against CalculiX, ANSYS/APDL, and corrected shell FEM.

Current trust principle:

- single tube EI/GJ is relatively trusted;
- equivalent beam has strong APDL parity;
- dual-beam no-wire and simple vertical-wire surrogate are useful;
- true wire, moment bookkeeping, local stress, buckling, and joints are not
  final truth yet.

Current route roles:

- daily screening: internal tubing / dual-beam model;
- Mac-local diagnostic: corrected mid-surface structured S4 shell;
- external confirmation: ANSYS/APDL spot checks;
- not recommended now: current Mac-safe C3D8R solid tube route and legacy
  triangular shell route.

The structure layer must label each result as:

- daily screening quality,
- FEM spot-check needed,
- final structure-grade.

## Stage 10: Final Verification

Only for finalists:

- 2D SU2 for selected airfoils,
- 3D SU2 / VSPAERO / CFD if needed,
- CalculiX / ANSYS spot checks,
- discrete CFRP layup,
- Tsai-Wu,
- buckling,
- joint checks,
- manufacturing package,
- drawing-ready VSP / SolidWorks package.

Final verification is not part of the MVP. It is the downstream signoff layer.

## Expected First Direction

Start with Stage 1: Fourier-AVL calibration.

Reason: Fourier must become a trustworthy fast spanload language before it is
used to guide the structure-budgeted loaded-Z search.
