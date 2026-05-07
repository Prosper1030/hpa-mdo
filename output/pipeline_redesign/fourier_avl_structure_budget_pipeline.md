# Fourier-AVL Structure-Budgeted Wing Pipeline

## Purpose

The next upstream HPA wing pipeline should stop treating loaded dihedral / requested Z as a late structural patch. It should search the requested loaded-shape state early, with the canonical dual-beam inverse-design workflow and a spar/tube mass budget, before final airfoil assignment.

The pipeline has two valid winners:

- **Aerodynamic best candidate**: lowest power among candidates that pass aerodynamic and airfoil-query quality checks.
- **Structure-feasible production candidate**: best power among candidates that also pass the structural budget contract and canonical jig-shape workflow.

If they differ, the production-facing baseline is the structure-feasible candidate. The aerodynamic best remains evidence, not a production baseline.

## Core Principle

Fourier, AVL, structure, and Tier2 airfoil data have different authority.

| Layer | Authority | Not Authority |
|---|---|---|
| Fourier | Controllable target spanload family and induced-drag idealization | Final CDi, final local Cl/Re, final ranking |
| AVL | Realized spanload, trim, local Cl/Re, CDi/e_CDi for low-speed lifting-line/panel screening | Final profile drag or structural feasibility |
| Canonical inverse design | Requested loaded shape -> jig shape -> realizable loaded shape, wire/clearance/manufacturing diagnostics | Airfoil profile selection |
| Tier2 full-alpha DB | Profile drag, alpha, Cm, stall margin at AVL actual Cl/Re | Spanload target or structural sizing truth |

## Proposed Pipeline

### Stage 0: Mission And Search Box

Define a `MissionContract` before geometry search:

- design mass / mass range
- cruise speed range and density
- required CL band
- pilot power / crank efficiency
- target distance or mission objective
- span, area, AR, taper, chord smoothness, twist bounds
- structural budget target, initially `spar_tube_mass_target_kg = 11.5`

This stage should emit a bounded design box, not a final candidate.

### Stage 1: Fourier Spanload Target Generation

Fourier enters here.

For each concept sample, generate a normalized half-span loading target using a low-dimensional Fourier family such as:

```text
Gamma_target(theta) = A1 sin(theta) + A3 sin(3theta) + A5 sin(5theta) + ...
```

The target must be converted into:

- station target `L'(y)` / normalized `cl*c`
- target `e_fourier`
- target outer loading ratio
- local Cl guard estimates
- target-vs-geometry feasibility hints

Fourier is a proposal, not proof. High `e_fourier` only says the target is attractive if the real wing can realize it.

### Stage 2: Smooth Geometry Realization

Build a smooth production-like geometry that attempts to realize the Fourier target:

- smooth monotone chord distribution
- bounded twist / incidence schedule
- preliminary airfoil placeholder or seed airfoils
- station table with span, chord, twist, provisional loaded Z
- no piecewise/faceted production planform if a smooth equivalent is available

This stage may use inverse-chord + residual twist, constrained splines, or a small optimizer. It must preserve manufacturable planform quality as a first-class metric.

### Stage 3: AVL Realization Check

AVL enters here.

Run AVL on the realized geometry and compute:

- `CL_req`, `alpha_at_CL_req`
- `CDi`, `e_CDi`
- local `Cl(y)` and `Re(y)`
- spanload `L'_AVL(y)`
- `target_vs_avl_rms`
- `target_vs_avl_outer_delta`
- local Cl utilization
- trim / stability diagnostics where relevant

AVL actual spanload becomes the aerodynamic screening truth. Fourier remains the reference target.

### Stage 4: Fourier-AVL Alignment Decision

Every candidate receives a spanload-alignment verdict:

| Condition | Decision |
|---|---|
| AVL contract sanity fails | Fix AVL setup before judging geometry |
| Fourier target high-e but AVL mismatch large | Target is not realized; update chord/twist/planform or relax Fourier coefficients |
| AVL e_CDi low and mismatch small | The target itself is probably not good for this geometry/mission |
| AVL e_CDi good and mismatch acceptable | Candidate can enter structural Z-state search |

Default rule: once AVL contract sanity passes, AVL is the authority for CDi, local Cl/Re, and airfoil work points. Fourier is wrong only in the sense that the target may be unrealizable or not worth chasing.

### Stage 5: Structure-Budgeted Z-State Search

Loaded Z enters here, before final airfoil optimization.

For each AVL-realized geometry, search requested loaded-shape states:

- target main/rear spar tip Z
- loaded dihedral curve family
- dihedral exponent / curvature descriptor
- root-to-tip Z distribution
- optional wire attach / support assumptions when exposed

Use the canonical workflow:

```text
requested cruise shape
-> scripts/direct_dual_beam_inverse_design.py
-> jig shape
-> realizable loaded shape
-> wire / clearance / manufacturing / CFRP checks
```

Do not use the Phase 9 proxy as structural truth. Do not use the Phase 10 sidecar alone as final truth.

The structural budget contract is applied here:

- spar/tube mass target, e.g. `<= 11.5 kg` preferred, `<= 11.75 kg` diagnostic line
- jig ground clearance minimum
- wire tension margin and slack check
- maximum jig prebend
- maximum jig curvature
- moment closure / torque convention check
- loaded-shape recovery error
- preliminary CFRP / manufacturing feasibility

Recent evidence shows why this must be early: the smooth baseline was heavy at low Z, but reached the old 11 kg tube line near target main-tip Z `2.65-2.70 m`. That is a geometry-state result, not an airfoil result.

### Stage 6: AVL Recheck On Feasible Loaded Shape

For each structure-feasible Z state, regenerate the AVL geometry with the feasible loaded shape and rerun AVL. This prevents airfoil selection from being based on the wrong local Cl/Re.

This stage emits the final zone envelopes:

- root / mid1 / mid2 / tip
- Re min / p50 / max
- Cl min / p50 / p90 / max
- Cm work point
- stall and utilization targets

### Stage 7: Tier2 Full-Alpha Airfoil Selection

Tier2 enters after feasible loaded shape and AVL actual Cl/Re are known.

For each feasible geometry/Z-state:

1. Query the Tier2 full-alpha DB using actual AVL local Cl/Re.
2. Build zone candidate pools by balanced score, mean Cd, p90 Cd, pass quality, archive quality, and reference airfoils.
3. Generate zone-level combinations.
4. Write AVL AFILEs and rerun AVL for shortlisted combinations.
5. Re-query profile drag using rerun AVL actual Cl.
6. Compute power, stall margin, max utilization, and quality flags.

The final aerodynamic metrics must use:

- AVL actual `CDi` / `e_CDi`
- Tier2 actual-query profile drag
- `CDi_conservative = 1.05 * CDi`
- mission drag budget band

### Stage 8: Dual Leaderboards And Recommendation

Produce two leaderboards:

- `aero_best`: best power with spanload and airfoil quality checks.
- `production_best`: best power with structural budget, jig feasibility, loaded-shape recovery, and airfoil quality.

Promotion rule:

```text
production-facing baseline = best candidate that passes structure-budget contract
```

If the aero best fails the structure budget, keep it as a research candidate and report the missing Z/mass/wire/jig condition needed to recover it.

## Required Outputs

Each run should produce:

- `fourier_targets.csv`
- `avl_realization_comparison.csv`
- `z_state_structure_budget_sweep.csv`
- `feasible_loaded_shape_shortlist.csv`
- `tier2_zone_envelopes.csv`
- `tier2_combo_results.csv`
- `aero_best_candidate.md`
- `structure_feasible_production_candidate.md`
- geometry exports for both best candidates

## Explicit Answers

**Where does Fourier enter?**
At Stage 1, as the controllable spanload target generator and induced-drag ideal reference.

**Where does AVL enter?**
At Stage 3 for realized spanload and CDi/e_CDi, again at Stage 6 after structure-feasible loaded Z, and again during Stage 7 airfoil-combination reruns.

**Where does Z-state / loaded shape enter?**
At Stage 5, before final airfoil optimization, as a searched design state constrained by real structural feasibility and mass budget.

**Where does jig shape enter?**
Inside Stage 5 through `scripts/direct_dual_beam_inverse_design.py`, which maps requested cruise shape to jig shape and realizable loaded shape.

**Where does the 11.5 kg structural budget enter?**
At Stage 5 as a structural budget contract. It is a preferred spar/tube mass target for Z-state selection, not a post-hoc report note.

**How do we decide whether Fourier or AVL is wrong when they differ?**
First verify AVL contract sanity. If AVL setup is sane, AVL is the authority for realized spanload, CDi, and local Cl/Re. The Fourier target is then treated as unrealized or over-ambitious unless geometry/twist updates can reduce the mismatch.

**What is the first MVP implementation step?**
Build a `structure_budgeted_z_state_search` wrapper that consumes one Fourier-AVL candidate section table plus AVL spanload, runs canonical inverse design across target loaded-Z states, and emits `z_state_structure_budget_sweep.csv` before Tier2 airfoil selection.
