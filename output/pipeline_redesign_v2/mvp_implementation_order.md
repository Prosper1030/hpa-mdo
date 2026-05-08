# MVP Implementation Order

## Boundary

This MVP sequence rewrites and integrates the design flow. It must not:

- run broad optimization,
- change production ranking,
- add hard gates,
- rerun CST/NSGA,
- promote unvalidated structural results to final truth.

## MVP 1: Fourier-AVL Calibration Module

### Goal

Understand whether AVL actual spanload can be described by low-order Fourier
coefficients, and build a bridge from commanded Fourier targets to AVL-realized
loading.

### Why First

Fourier is useful only if it means the same thing as AVL in this repo. If we use
uncalibrated Fourier to guide structure, we may optimize toward a spanload that
the realized geometry cannot actually produce.

### Minimum Work

1. Define `eta`, `theta`, `Lprime`, `cl*c`, circulation proxy, normalized
   loading, and half-span/full-span convention.
2. Fit AVL actual spanload into `A1/A3/A5/A7`.
3. Compare Fourier theoretical `e` and bending proxy against AVL `CDi/e_CDi`
   and AVL bending proxy.
4. Write command-vs-realized mapping rows.
5. Diagnose mismatch source.

### Expected Outputs

- `spanload_definition.md`
- `avl_to_fourier_fit.csv`
- `fourier_command_to_avl_realized.csv`
- `fourier_avl_calibration_report.md`
- `recommended_fourier_bridge.md`

### Acceptance

- At least one current baseline case can be fit into Fourier coefficients.
- The report clearly states whether mismatch is definition-level, geometry
  authority-level, airfoil/alpha_L0-level, loaded-dihedral-level, or AVL setup
  level.
- No ranking, hard gate, or optimizer behavior changes.

## MVP 2: Structure-Budgeted Z-State Search v2

### Goal

Use calibrated spanload families and the canonical inverse-design route to find
plausible `6-7 deg` total effective loaded-shape states under an `11.5 kg` class
tube/spar budget.

### Why Second

The loaded shape and structure budget decide which local `Cl/Re` envelope is
real. Airfoil selection should wait until this is known.

### Minimum Work

1. Use Stage 1 calibrated spanload families, not raw uncalibrated Fourier.
2. Use canonical `direct_dual_beam_inverse_design` route.
3. Separate Z definitions:
   - aerodynamic surface tip z,
   - main beam tip z,
   - rear beam tip z,
   - built-in geometric z,
   - elastic deflection z,
   - total cruise effective dihedral.
4. Search loaded `z(y)` families, not only scalar tip z.
5. Report tube/spar mass with explicit mass basis.
6. Keep `77 kg` results out of physical-truth interpretation.

### Expected Outputs

- `z_state_structure_budget_sweep.csv`
- `feasible_loaded_shape_shortlist.csv`
- `z_definition_audit.md`
- `recommended_loaded_z_states.md`

### Acceptance

- The sweep can identify whether any `6-7 deg` total effective dihedral state is
  plausible under the current mass budget.
- If none pass, the report names the blocker: clearance, wire, moment closure,
  geometry validity, mass basis, or load mismatch.
- No hard gates are changed.

## MVP 3: AVL Recheck On Feasible Loaded Shapes

### Goal

Confirm aerodynamic consequences of structurally plausible loaded shapes.

### Minimum Work

1. Export each feasible or near-feasible loaded shape.
2. Run AVL on that actual loaded geometry.
3. Compute `CDi`, `e_CDi`, spanload, local `Cl/Re`, stall margin, and bending
   proxy.
4. Compare against pre-structure AVL.

### Expected Outputs

- `loaded_shape_avl_recheck.csv`
- `loaded_shape_spanload_comparison.csv`
- `loaded_shape_local_cl_re_envelope.csv`
- `loaded_shape_aero_recheck_report.md`

### Acceptance

- Each structurally plausible Z state has an AVL actual spanload and local
  `Cl/Re` envelope.
- Bad aero consequences are reported, not hidden.

## MVP 4: Tier2 Airfoil Selection After Feasible Loaded Shape

### Goal

Select airfoils using actual `Cl/Re` from structurally feasible loaded shapes.

### Minimum Work

1. Read Tier2 full-alpha database.
2. Build zone-level root/mid1/mid2/tip requirements from Stage 6 actual `Cl/Re`.
3. Run capped combo search.
4. Rerun AVL with selected `AFILE`s.
5. Integrate profile drag using AVL actual local Cl.
6. Report raw best and conservative production-quality best.

### Expected Outputs

- `tier2_loaded_shape_airfoil_assignment.json`
- `tier2_loaded_shape_combo_search.csv`
- `tier2_loaded_shape_profile_drag.csv`
- `tier2_loaded_shape_airfoil_report.md`

### Acceptance

- The selected airfoil assignment is based on actual loaded-shape AVL `Cl/Re`,
  not Fourier target Cl.
- No broad CST/NSGA rerun is performed.

## MVP 5: Aero-Structure Closure

### Goal

Check whether selected airfoils and updated spanload still satisfy structure,
mass, jig, clearance, and wire constraints.

### Minimum Work

1. Rerun AVL with selected airfoils.
2. Recompute spanload and load mapping.
3. Rerun structure response with the same mass/recipe basis.
4. Compare deflection, loaded shape, wire tension, clearance, and mass against
   MVP 2.
5. If mismatch is above tolerance, recommend loopback target.

### Expected Outputs

- `aero_structure_closure_summary.csv`
- `aero_structure_closure_report.md`
- `closure_loopback_recommendation.md`

### Acceptance

- Closure status is one of:
  - `closed_for_screening`,
  - `minor_mismatch`,
  - `loop_back_to_fourier_geometry`,
  - `loop_back_to_z_state`,
  - `loop_back_to_airfoil_selection`.

## Recommended Immediate Next Task

Start with MVP 1: Fourier-AVL calibration.

Do not run additional Z sweeps first. More Z sweeps before Fourier-AVL
calibration risk searching structure against a spanload language that is not yet
aligned with AVL.
