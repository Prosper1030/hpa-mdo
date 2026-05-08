# Workstreams

## Workstream 1: Fourier-AVL Control

### Purpose

Make Fourier useful as a fast spanload command language by continuously
calibrating it against AVL actual spanload.

### Core Work

- Maintain spanload definitions and half-span/full-span conventions.
- Fit AVL actual loading into Fourier coefficients.
- Maintain commanded-to-realized correction rows.
- Diagnose outer-underloading, local Cl limits, and geometry authority limits.
- Feed corrected spanload families into structural search.

### Success Output

- A bridge that says which Fourier commands are usable, corrected, or
  impossible for the current geometry family.

## Workstream 2: Structure-Budgeted Loaded Shape

### Purpose

Find loaded `z(y)` states that satisfy the structural budget while preserving
mission/aero intent.

### Core Work

- Keep aerodynamic surface z, beam-line z, built-in z, elastic z, and total
  loaded z separate.
- Prioritize `6-7 deg` total cruise effective dihedral.
- If `6-7 deg` fails, search nearby practical compromises and quantify penalty.
- Use canonical inverse design / jig shape route.
- Track mass basis explicitly.
- Split clearance, wire, force closure, and moment closure into separate
  evidence channels.

### Success Output

- A shortlist of loaded-shape candidates with explicit mass, clearance, wire,
  force closure, moment bookkeeping, and trust labels.

## Workstream 3: Smooth Geometry

### Purpose

Keep the geometry production-facing while allowing enough aerodynamic authority
to realize the desired spanload.

### Core Work

- Maintain smooth monotone chord.
- Maintain smooth twist.
- Avoid final faceted chord.
- Export VSP `production_inspection`.
- Export AVL parity geometry.
- Diagnose whether chord, twist, or airfoil camber authority is insufficient.

### Success Output

- Smooth geometry that AVL can evaluate and production inspection can review.

## Workstream 4: Airfoil Database Selection

### Purpose

Use Tier2 full-alpha airfoil evidence after the loaded-shape AVL `Cl/Re`
envelope is known.

### Core Work

- Build zone requirements from actual loaded-shape AVL `Cl/Re`.
- Separate raw best and conservative best.
- Repair or reject query warnings.
- Avoid broad CST/NSGA unless Tier2 coverage is proven insufficient.
- Rerun AVL with selected airfoils.
- Report profile drag, `CD0_total`, nominal power, conservative power, and stall
  margin.

### Success Output

- A query-pass conservative airfoil assignment, plus raw-best diagnostics if
  useful.

## Workstream 5: Aero-Structure Closure

### Purpose

Prove that the selected airfoils, actual spanload, structural response, mass,
clearance, and wire state still agree after coupling.

### Core Work

- Rerun AVL with selected airfoils.
- Recompute spanload and bending proxy.
- Rerun structural response.
- Compare mass, deflection, clearance, wire, power, and spanload against the
  previous accepted state.
- Loop back when tolerances are exceeded.

### Success Output

- A closure status that is either production-facing, credible compromise,
  screening-only, or blocked with evidence.

## Workstream 6: Structural Model Trust / FEM Calibration

### Purpose

Keep fast structure screening honest without turning FEM into broad search.

### Core Work

- Use internal dual-beam/tube model for daily screening.
- Use corrected shell/APDL/CalculiX for selected spot checks.
- Maintain trust labels.
- Diagnose true wire, moment bookkeeping, support reaction, root torque, local
  stress, buckling, and joint limitations separately.

### Success Output

- A candidate-specific structural trust statement and FEM spot-check plan.

## Workstream 7: Final Candidate Packaging

### Purpose

Turn the best closed candidate into an engineering review package.

### Required Package

- mission power summary,
- smooth geometry exports,
- AVL parity export,
- actual spanload and Fourier bridge evidence,
- loaded-shape / jig-shape artifacts,
- tube/spar mass and structural feasibility summary,
- airfoil assignment and polar quality summary,
- closure report,
- trust labels,
- FEM spot-check plan,
- final recommendation.

### Success Output

- One recommended production-facing candidate, or a blocker package explaining
  why no such candidate is available under the current assumptions.
