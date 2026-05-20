# HPA Operating Condition Lock

Verdict: `phase0_hard_stop_condition_mismatch`

This report is the Phase 0 lock for rebuilding the WO-006 true Baseline A
OpenFOAM grid-independence study as an HPA-specific aviation CFD verification
workflow. It intentionally does not proceed to mesh audit, mesh generation,
solver runs, AoA sweep, or design-power update.

## Decision

Do not start the Coarse / Medium / Fine grid family yet.

The current OpenFOAM candidate and the original design estimate are not on the
same operating-condition basis:

| item | original design estimate | current OpenFOAM candidate | status |
|---|---:|---:|---|
| density `rho` | `1.18 kg/m^3` | `1.225 kg/m^3` | mismatch |
| speed `V` | `6.6 m/s` | `6.5 m/s` | mismatch |
| dynamic viscosity `mu` | `1.7228e-5 Pa*s` | `1.78936e-5 Pa*s` from `rho * nu` | mismatch |
| kinematic viscosity `nu` | `1.459999e-5 m^2/s` | `1.4607e-5 m^2/s` | near match |
| AoA convention | `aoa_deg=0.18015` in loaded-shape AVL/Tier2 row | `AOA_DEG=0.18`; `U`, `dragDir`, and `liftDir` are rotated by this angle | near match, must keep explicit |
| full reference area `Sref` | `33.420059598 m^2` | `33.420059598 m^2` on full-wing mirror route | match |
| reference chord `Cref` | `1.003721543 m` | `1.003721543 m` | match |
| span convention | full span `34.332286 m`; half span `17.166143 m` | full-wing mirror route spans `y=-17.166143..17.166143 m` | match for mirrored route |
| design lift coefficient | `CL=1.16853` from the AVL loaded-shape screening row | stable OpenFOAM route gives `CL_primary=1.133291` at same nominal AoA | not CL-matched |
| turbulence / transition model | original design estimate is AVL plus Tier2/XFOIL profile drag, not 3D RANS | OpenFOAM uses fully turbulent Spalart-Allmaras RANS, no transition model | model mismatch |

Because the Phase 0 instruction says to stop if any condition differs from the
original design estimate, this is a hard stop. Any later grid family must first
choose and document one target operating basis, then regenerate all meshes and
solver controls on that basis.

## Sources Checked

- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_loaded_shape_avl_recheck/loaded_shape_local_cl_re_envelope.csv`
- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_selected_avl_recheck.csv`
- `output/go_mode_main_wing_candidate/final_candidate_package/geometry_exports/avl_parity/current_avl_compromise_conservative_closed/geometry_manifest.json`
- `scripts/run_wo006_true_baseline_openfoam_route_smoke.py`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_solver_stability/stable_route_smoke_report.md`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_grid_convergence/grid_convergence_report.md`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/drag_power_audit/original_drag_power_source_report.md`

## Operating Basis Details

### Original Design Estimate

The traceable original drag/power estimate is the `conservative_best` loaded
shape / Tier2 row:

- `rho = 1.18 kg/m^3`
- `V = 6.6 m/s`
- `mu = 1.7228e-5 Pa*s`
- `dynamic_pressure = 25.7004 Pa`
- `aoa_deg = 0.18015 deg`
- `CL = 1.16853`
- `CDi = 0.0127613`
- `profile_cd = 0.009368851143241826`
- `CD0_total = 0.013258730502038055`
- `CD_total = 0.026020030502038057`
- `P_crank = 174.60027944116567 W`

This is a screening closure: AVL induced drag plus Tier2/XFOIL-style wing
profile drag plus a lumped non-wing reserve. It is not 3D CFD truth.

### Current OpenFOAM Candidate

The current stable OpenFOAM route-smoke basis is:

- `rho = 1.225 kg/m^3`
- `V = 6.5 m/s`
- `nu = 1.4607e-5 m^2/s`
- `mu = rho * nu = 1.78936e-5 Pa*s`
- `AoA = 0.18 deg`
- `Sref = 33.420059598 m^2`
- `Cref = 1.003721543 m`
- `full-wing mirror` with no root-symmetry force group
- `SpalartAllmaras` RANS
- accepted route-smoke: `CD_primary=0.03276165`, `CL_primary=1.133291`

The later grid-convergence attempt kept this current OpenFOAM basis and did not
prove grid independence.

## Reynolds Number Lock

Using the true Baseline A station chords:

| station `y` m | chord m |
|---:|---:|
| `0.000000` | `1.256773` |
| `2.746583` | `1.171565` |
| `6.008150` | `1.067328` |
| `8.926394` | `0.970372` |
| `12.016300` | `0.862164` |
| `14.076237` | `0.784941` |
| `15.449529` | `0.729402` |
| `16.307836` | `0.691495` |
| `17.166143` | `0.645004` |

| basis | Re at tip chord | Re at root chord | Re at `Cref` |
|---|---:|---:|---:|
| original design estimate | `2.916e5` | `5.681e5` | `4.537e5` |
| current OpenFOAM candidate | `2.870e5` | `5.593e5` | `4.466e5` |

The Reynolds ranges are close, but they are not identical. For low-Re HPA wing
work, the difference is not just bookkeeping because transition, laminar
separation bubble behavior, and profile drag can move inside this band.

## AoA Convention

The current OpenFOAM script rotates the freestream and coefficient axes by the
same `AOA_DEG`:

- `U = (V*cos(alpha), 0, V*sin(alpha))`
- `dragDir = (cos(alpha), 0, sin(alpha))`
- `liftDir = (-sin(alpha), 0, cos(alpha))`

This is internally consistent for the current OpenFOAM case. It is not yet a
complete convention proof against the original AVL/Tier2 body-axis basis,
because the original design estimate came from AVL loaded-shape analysis and
Tier2 profile-drag closure, not the same OpenFOAM geometry/BC model.

## Full-Wing / Half-Wing Convention

The current accepted stable OpenFOAM run is a full-wing mirrored route with:

- domain span `y=-17.166143..17.166143 m`
- full-wing `Sref = 33.420059598 m^2`
- `primary = airfoil_upper + airfoil_lower`
- `total = primary + physical_tip_left + physical_tip_right + te_wall`

The later grid-convergence attempt used artificial tip closures as
`symmetryPlane` and defined physical drag as `primary + te_wall`, excluding the
artificial mirrored tip closures. That may be a useful diagnostic to remove
side-patch contamination, but it is not sufficient for the requested HPA
verification workflow because tip vortex behavior must be compared across the
grid family.

## Turbulence / Transition Model Assessment

The current OpenFOAM model is fully turbulent Spalart-Allmaras RANS with no
transition model.

For an HPA wing with station Reynolds numbers around `2.9e5..5.7e5`, this is
not a final drag-trust model by itself. Low-Re airfoils can have large laminar
regions, transition sensitivity, and laminar separation bubbles. A fully
turbulent SA run can be useful as a bounded robustness / conservative
route-smoke model, but it should not be treated as a release-grade HPA drag
verification unless the workflow either:

- explicitly chooses fully turbulent RANS as the design assumption and documents
  the drag conservatism risk, or
- adds a transition-aware model / external transition evidence and compares Cp,
  Cf, wake, and separation behavior.

## Phase 0 Blockers

1. `rho`, `V`, and `mu` differ from the original design estimate.
2. The current OpenFOAM route is not CL-matched to the original `CL=1.16853`;
   it only uses nearly the same AoA.
3. The current grid-convergence route suppresses physical tip-vortex behavior
   with artificial symmetry treatment, conflicting with the requested tip-vortex
   comparison gate.
4. Fully turbulent SA is not by itself an HPA low-Re transition-credible drag
   model.
5. The existing grid-convergence result already failed solver stability and
   fine-grid mesh quality, so it cannot be reused as the final same-family
   study.

## Required Next Action

Before Phase 1, choose one operating basis:

1. `original_design_basis`: `rho=1.18 kg/m^3`, `V=6.6 m/s`,
   `mu=1.7228e-5 Pa*s`, original AVL/Tier2 AoA convention, `CL_design=1.16853`.
2. `current_openfoam_basis`: `rho=1.225 kg/m^3`, `V=6.5 m/s`,
   `nu=1.4607e-5 m^2/s`, current OpenFOAM AoA convention, then document that it
   intentionally supersedes the original design estimate for CFD verification.

After that decision, rebuild all Coarse / Medium / Fine cases from the same
geometry, same BC, same force definitions, same reference quantities, same
turbulence/transition assumption, and a mesh strategy that preserves physical
near wake and tip-vortex diagnostics.

Until then:

- do not claim grid independence,
- do not trust `CD approx 0.0315`,
- do not update design power from `174 W`,
- do not start an AoA sweep.
