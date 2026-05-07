# Dual-Beam Structural Model Inventory

## Executive Read

- `dual_beam_production` is the current repo mainline structural truth for inverse design, jig shape, loaded shape, and downstream CFRP or discrete-layup workflow.
- `equivalent_beam` was not retired because it was numerically broken. It was retained as a legacy parity and regression route after it passed apples-to-apples ANSYS parity for its own single-equivalent-beam assumptions.
- Existing ANSYS and CalculiX evidence is mixed by model family. Some checks are clean solver/export parity checks, some are model-form spot checks, and some are shell-mesh sanity runs. They must not be treated as the same kind of evidence.
- The current validation gap is not “does any structural code run?” The real gap is “do the current front spar + rear spar + wire + torque + rib-link assumptions match an external beam or FEM model under the same benchmark contract?”

## Quick Matrix

| Model / workflow | Family | Current repo role | Strongest evidence | Main blind spot |
| --- | --- | --- | --- | --- |
| `equivalent_beam` / tube beam | Single equivalent beam, 6-DOF Timoshenko FEM | Legacy parity and regression | `docs/ansys_equivalent_beam_validation_pass.md`, `output/blackcat_004/ansys/crossval_report.txt` | No explicit front/rear load sharing, wire-truss behavior, or rib-link topology |
| Concept `jig_shape_gate` proxy | Closed-form beam proxy with wire-relief correction | Concept-stage geometry screening only | Formula-level screening in `src/hpa_mdo/concept/jig_shape.py` | Not a dual-beam structural solve |
| `dual_spar` parity / spot-check model | Two beam lines + rigid links | Higher-fidelity inspection and apples-to-apples ANSYS parity mode | `output/_archive_pre_2026_04_15/blackcat_004_internal_dual_beam_smoke_with_ansys/dual_beam_internal_report.txt` | Still idealized; joint-only links, no explicit production wire-truss or self-weight ownership |
| `dual_beam_production` | Explicit two-beam Timoshenko kernel with exact constraints | Current production truth | `src/hpa_mdo/structure/dual_beam_mainline/*`, current mainline docs, inverse-design workflow | External benchmark ladder not finished; torque ownership and moment bookkeeping still need controlled validation |
| Frozen-load inverse design / jig workflow | Workflow on top of `dual_beam_production` | Current mainline geometry backout | `CURRENT_MAINLINE.md`, `src/hpa_mdo/structure/inverse_design.py`, `output/phase10_3_smooth_z_state_mass_sweep/*` | Depends on the production structural model; not an independent structural truth model |
| ANSYS/APDL exporters | External beam-model deck generator | Export / compare contract | `src/hpa_mdo/structure/ansys_export.py`, `scripts/ansys_crossval.py`, `scripts/ansys_dual_beam_production_check.py` | Production torque contract needs a fresh audit before calibration work |
| Gmsh -> CalculiX structural check | Shell-plus-beam external FEM spot-check | Local structural spot-check | `docs/hi_fidelity_validation_stack.md`, `output/blackcat_004/hifi_support_reaction_rerun_20260418/structural_check.json` | Not yet a clean beam benchmark or final external truth |
| Validation docs and tests | Regression and contract checks | Preserve semantics and compare helpers | `tests/test_dual_beam_mainline.py`, `tests/test_ansys_crossval.py`, `tests/test_hifi_structural_check.py` | Tests prove code semantics, not final physical validity |

## 1. `equivalent_beam` / tube-beam model

- Files:
  - `src/hpa_mdo/structure/fem/assembly.py`
  - `src/hpa_mdo/structure/components/spar_props.py`
  - `src/hpa_mdo/structure/groups/main.py`
  - `src/hpa_mdo/structure/spar_model.py`
  - `src/hpa_mdo/structure/optimizer.py`
  - `scripts/ansys_crossval.py`
  - `docs/ansys_equivalent_beam_validation_pass.md`
  - `output/blackcat_004/ansys/crossval_report.txt`
- Model family: single equivalent beam; 6-DOF Timoshenko beam FEM with equivalent section properties from a main spar + rear spar section reduction.
- Mechanics / assumptions:
  - `DualSparPropertiesComp` and `compute_dual_spar_section()` collapse the front and rear tubes into one beam section using area summation, the parallel-axis theorem for bending, and a rigid-rib torsional coupling term with optional knockdown.
  - `SpatialBeamFEM` solves a half-span beam with one structural line and 6 DOF per node.
  - This is a “same EI/GJ, same section mass, same beam line” representation, not an explicit two-line structure.
- Load assumptions:
  - Lift is applied as nodal `Fz`.
  - Aerodynamic torque is applied as nodal `My` on the equivalent beam.
  - Rear-spar self-weight can be collapsed into an equivalent torsional load about the main beam.
- Boundary conditions:
  - Root fixed in all 6 DOF.
  - Lift wire represented as a vertical displacement constraint at the mapped beam node.
- Wire / support assumptions:
  - The wire is not an explicit cable or truss element in the legacy parity path.
  - Wire support mainly acts as a kinematic vertical support and optional axial precompression estimate.
- Torque / `Cm` assumptions:
  - Aerodynamic pitching-moment effect is treated as a spanwise torsional-moment channel on the equivalent beam.
  - There is no explicit front/rear vertical force couple.
- What has ANSYS/APDL parity:
  - Historical Phase I parity PASS against ANSYS on the same equivalent-beam assumptions:
    - tip deflection error `0.67%`
    - max vertical displacement error `0.67%`
    - support reaction error `~0.00%`
    - spar mass error `0.17%`
- Known evidence / error levels:
  - Evidence root: `docs/ansys_equivalent_beam_validation_pass.md`
  - Current default report artifact: `output/blackcat_004/ansys/crossval_report.txt`
  - Stress extraction is explicitly provisional and non-gating.
- What it can be trusted for:
  - Global equivalent `EI`, `GJ`, mass bookkeeping, and support reaction regression under the equivalent-beam assumptions.
  - Legacy reference gates that the repo still keeps beside the dual-beam path.
  - Detecting drift in the old export/compare contract.
- What it cannot be trusted for:
  - Front/rear spar load sharing.
  - Explicit wire-truss behavior or tension-only support behavior.
  - Rear-spar outboard amplification.
  - Rib or link topology sensitivity.
  - Torque ownership between a front spar and rear spar.
  - Present-day sign-off of jig-shape or inverse-design results.

## 2. Concept `jig_shape_gate` proxy

- Files:
  - `src/hpa_mdo/concept/jig_shape.py`
  - `src/hpa_mdo/concept/geometry.py`
  - `src/hpa_mdo/concept/lift_wire.py`
  - `src/hpa_mdo/concept/config.py`
  - `README.md` concept-line discussion around `jig_shape_gate`
- Model family: concept-stage proxy; closed-form Euler-Bernoulli-like cantilever estimate with a wire-relief correction.
- Mechanics / assumptions:
  - Unbraced tip deflection is estimated as a uniform-load cantilever:
    - `delta_tip ~= q L^4 / (8 E I)` times a user-configurable taper correction factor.
  - `I` is estimated from thin-wall root-tube geometry, with an optional parallel-axis contribution if the concept has two spars with a configured vertical separation.
  - Lift-wire relief is estimated by the classic point-load-on-cantilever deflection formula at the attachment station.
- Load assumptions:
  - Each wing carries a uniform distributed 1g load derived from gross mass.
  - One effective lift-wire support fraction can relieve a configurable fraction of cruise lift.
- Boundary conditions:
  - Root-fixed cantilever.
- Wire / support assumptions:
  - One coarse effective wire support per wing.
  - No explicit truss stiffness, no tension-only state solve, no reaction partition.
- Torque / `Cm` assumptions:
  - No explicit aerodynamic torque or twist ownership model.
- What has ANSYS/APDL or CalculiX parity:
  - None in this repo.
- Known evidence / error levels:
  - This is intentionally a concept-screening proxy, not an externally benchmarked structural model.
- What it can be trusted for:
  - Fast order-of-magnitude screening of whether a concept is obviously too flexible.
  - Showing that wire relief matters for HPA-like wings.
- What it cannot be trusted for:
  - Any detailed dual-beam calibration claim.
  - Any front/rear spar load-sharing conclusion.
  - Any torque, twist, rear-tip, or rib-link judgment.
  - Any downstream jig-shape or loaded-shape sign-off.

## 3. `dual_spar` parity / spot-check model

- Files:
  - `src/hpa_mdo/structure/dual_beam_analysis.py`
  - `src/hpa_mdo/structure/ansys_export.py` in `dual_spar` mode
  - `docs/dual_spar_spotcheck_workflow.md`
  - `scripts/ansys_dual_spar_spotcheck.py`
  - `output/_archive_pre_2026_04_15/blackcat_004_internal_dual_beam_smoke_with_ansys/dual_beam_internal_report.txt`
  - `output/_archive_pre_2026_04_15/blackcat_004_dual_beam_refinement/ansys_refined/spotcheck_summary.txt`
- Model family: explicit two-beam beam FEM and matching ANSYS BEAM188 inspection model.
- Mechanics / assumptions:
  - Two beam lines are modeled explicitly at main-spar and rear-spar locations.
  - The internal analysis path uses a penalty-coupled rigid-link assumption between main and rear nodes at joint stations.
  - The ANSYS parity mode uses equal-DOF link constraints at joint positions only.
- Load assumptions:
  - Lift is applied on the main spar line.
  - Aerodynamic torque is represented as a front/rear vertical force couple about the main spar.
  - In parity mode, explicit spar self-weight is disabled so the internal and ANSYS decks compare the same load contract.
- Boundary conditions:
  - Root fixed on both spars.
  - Lift wire represented as `UZ = 0` on the main spar at the wire node.
- Wire / support assumptions:
  - Wire remains a vertical support condition in this parity path, not an explicit truss solve.
- Torque / `Cm` assumptions:
  - Torque is represented as a vertical force couple, not as a main-beam torsional DOF.
- What has ANSYS/APDL parity:
  - For the inspected baseline smoke, internal dual-beam vs dual-spar ANSYS matched closely:
    - main-tip deflection error `0.56%`
    - max `|UZ|` error `0.51%`
    - support reaction error `0.00%`
    - spar mass error `0.18%`
- Known evidence / error levels:
  - The refined dual-spar spot-check summary later reported:
    - tip discrepancy `14.83%`
    - max `|UZ|` discrepancy `37.86%`
    - reaction and mass still consistent
    - overall classification `MODEL-FORM RISK`
  - This is evidence that equivalent-beam parity does not automatically validate two-beam adequacy for ranking or feasibility.
- What it can be trusted for:
  - Apples-to-apples beam-model parity against ANSYS for a two-line topology.
  - Diagnosing rear-tip amplification and topology sensitivity.
  - Checking whether higher-fidelity beam topology could change active constraints or ranking.
- What it cannot be trusted for:
  - Final production truth for the current mainline.
  - Explicit wire-truss or pretension behavior.
  - Final rib stiffness or finite rib-bay behavior.
  - Final composite stress or shell hotspot truth.

## 4. `dual_beam_production`

- Files:
  - `src/hpa_mdo/structure/dual_beam_mainline/types.py`
  - `src/hpa_mdo/structure/dual_beam_mainline/builder.py`
  - `src/hpa_mdo/structure/dual_beam_mainline/load_split.py`
  - `src/hpa_mdo/structure/dual_beam_mainline/constraints.py`
  - `src/hpa_mdo/structure/dual_beam_mainline/solver.py`
  - `src/hpa_mdo/structure/dual_beam_mainline/recovery.py`
  - `src/hpa_mdo/structure/dual_beam_mainline/optimizer_view.py`
  - `src/hpa_mdo/structure/dual_beam_mainline/api.py`
  - `scripts/ansys_dual_beam_production_check.py`
  - `scripts/direct_dual_beam_inverse_design.py`
  - `output/_archive_pre_2026_04_15/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
  - `output/_archive_pre_2026_04_15/blackcat_004_dual_beam_production_check/production_vs_dual_spar_ansys_surrogate.txt`
  - `output/phase13_moment_closure_debug/moment_closure_diagnosis.md`
  - `output/phase13_moment_ownership_ab_test/torque_ownership_diagnosis.md`
- Model family: explicit two-beam Timoshenko beam kernel with exact constraint rows, explicit wire-truss support, and separate recovery/optimizer/report channels.
- Mechanics / assumptions:
  - Main and rear beams each carry their own `A`, `Iy`, `Iz`, `J`, density, and allowable stress arrays.
  - The solver assembles both beam chains, then solves an exact-constraint saddle-point system for displacements and constraint multipliers.
  - Default production topology uses:
    - root fixed on both spars
    - `WIRE_MAIN_TRUSS` explicit truss wire support
    - `JOINT_ONLY_OFFSET_RIGID` link mode at joint stations
  - Recovery computes root reactions, wire reactions, link resultants, provisional stress, wire precompression, and report metrics.
  - Equivalent-beam gates are retained beside the dual-beam run as legacy reference checks.
- Load assumptions:
  - In current `DUAL_BEAM_PRODUCTION` mode:
    - lift -> main beam `Fz`
    - aerodynamic torque -> main-beam `My` about the main spar
    - main spar self-weight -> main beam `Fz`
    - rear spar self-weight -> rear beam `Fz`
    - collapsed rear-gravity torque -> disabled
- Boundary conditions:
  - Root fixed on both spars.
  - Default wire mode is explicit truss, not just `UZ = 0`.
  - Link topology is offset-rigid at joint locations, not dense all-node rigid coupling.
- Wire / support assumptions:
  - Explicit wire unstretched length can be back-computed from configured pretension.
  - Wire validity checks track tension-only and allowable-tension behavior.
  - This is closer to the real current workflow than legacy vertical-support parity.
- Torque / `Cm` assumptions:
  - The production kernel currently stores aerodynamic pitching effect as `torque_per_span_nmpm` and, by mode definition and tests, applies it as `main_beam_my_about_main_spar`.
  - The raw 2D airfoil `Cm` distribution is not retained at this layer.
- What has ANSYS/APDL or CalculiX parity:
  - No finished apples-to-apples external benchmark ladder yet.
  - The archived production-vs-dual-spar-ANSYS surrogate comparison is inspection-only and shows meaningful mismatch:
    - main-tip deflection error `19.21%`
    - support reaction error `11.34%`
    - mass error `0.19%`
    - verdict `INFO ONLY`
- Known evidence / error levels:
  - `moment_closure` debug shows the current residual is dominated by moment bookkeeping, not force equilibrium:
    - baseline moment residual `1707.206 N*m`
    - `Cm-off` residual drops to `246.776 N*m`
  - Torque-ownership A/B shows `front_rear_vertical_couple` gives the smallest physically meaningful residual among tested modes, but that mode is not yet the frozen production contract.
  - Engineering caution:
    - `types.py` and `tests/test_dual_beam_mainline.py` freeze production torque ownership as `main_beam_my_about_main_spar`.
    - `scripts/ansys_dual_beam_production_check.py` report text and `ansys_export.py` comments still talk about an aerodynamic torque couple in places.
    - The current APDL writer for `dual_beam_production` emits nodal `FZ` lines only, so the production external-torque contract must be audited before it is used as calibration truth.
- What it can be trusted for:
  - Current repo internal ranking and feasibility workflow, because this is the stated mainline truth.
  - Current inverse-design and jig/loaded-shape artifact generation.
  - Internal diagnostics for wire tension, root reactions, link hotspots, and rear amplification trends.
- What it cannot be trusted for:
  - Final external validation of torque ownership.
  - Final calibration of rib-link stiffness or dense rib-bay transfer.
  - Final shell/solid or discrete-layup hotspot truth.
  - A hard external sign-off claim before a controlled benchmark ladder is run.

## 5. Frozen-load inverse design / jig-shape workflow

- Files:
  - `src/hpa_mdo/structure/inverse_design.py`
  - `scripts/direct_dual_beam_inverse_design.py`
  - `scripts/validate_smooth_tier2_dual_beam_structure.py`
  - `CURRENT_MAINLINE.md`
  - `output/phase10_3_smooth_z_state_mass_sweep/z_state_mass_sweep_summary.md`
- Model family: geometry backout and validation workflow layered on top of the structural kernel.
- Mechanics / assumptions:
  - Build a target loaded shape.
  - Run the structural solve under frozen loads.
  - Back out the jig shape by subtracting solved translations from the target loaded shape.
  - Recheck loaded-shape match, ground clearance, and simple manufacturing metrics.
- Load assumptions:
  - Inherits whichever aerodynamic load source the workflow freezes for the case.
  - Current mainline often uses AVL-first or candidate-owned rerun loads, then solves the structural inverse-design problem.
- Boundary conditions / wire / torque assumptions:
  - Inherit the currently selected dual-beam mode, which is normally `dual_beam_production`.
- What has ANSYS/APDL or CalculiX parity:
  - None as an independent workflow-level validation.
  - It relies on the structural model underneath it.
- Known evidence / error levels:
  - The z-state sweep shows that requested loaded `z` state strongly changes selected mass, clearance, and jig pre-bend.
  - That is useful workflow evidence, not a solver-calibration proof.
- What it can be trusted for:
  - Producing current mainline jig/loaded artifacts relative to the current internal model.
  - Showing sensitivity of manufacturability and clearance to requested shape state.
- What it cannot be trusted for:
  - Independent proof that the structural model form is externally validated.
  - Independent proof that one selected jig shape is physically right in ANSYS or CalculiX.

## 6. ANSYS / APDL export and compare routes

- Files:
  - `src/hpa_mdo/structure/ansys_export.py`
  - `scripts/ansys_crossval.py`
  - `scripts/ansys_dual_spar_spotcheck.py`
  - `scripts/ansys_dual_beam_production_check.py`
  - `scripts/ansys_compare_results.py`
  - `tests/test_ansys_crossval.py`
  - `tests/test_ansys_dual_spar_spotcheck.py`
  - `tests/test_ansys_dual_beam_production_check.py`
- Model family: external beam-model deck generator and post-processor.
- Mechanics / assumptions:
  - `equivalent_beam` export: one equivalent BEAM188 line using equivalent section properties and equivalent nodal loads.
  - `dual_spar` export: two beam lines plus parity-style equal-DOF links at joint stations.
  - `dual_beam_production` export: two beam lines plus offset-rigid `CERIG` links.
- Load assumptions:
  - Equivalent mode is the clean historical apples-to-apples legacy parity path.
  - Dual-spar mode is the clean historical apples-to-apples two-beam parity path.
  - Production mode is intended to follow current production load ownership, but the torque channel needs a fresh contract audit before using it as calibration truth.
- What has parity:
  - Equivalent-beam parity PASS.
  - Dual-spar beam-parity smoke is close for the equivalent optimum.
  - Production export has inspection evidence only.
- What it can be trusted for:
  - Reproducible export of geometry, section properties, and support/load contracts by mode.
  - Beam-model comparison once the benchmark case is frozen.
- What it cannot be trusted for:
  - Automatic validation of the production model form just because a deck exists.
  - Final truth until the applied production torque contract is explicitly verified.

## 7. Gmsh -> CalculiX structural check route

- Files:
  - `src/hpa_mdo/hifi/gmsh_runner.py`
  - `src/hpa_mdo/hifi/calculix_runner.py`
  - `src/hpa_mdo/hifi/structural_check.py`
  - `scripts/hifi_mesh_step.py`
  - `scripts/hifi_structural_check.py`
  - `scripts/export_dual_beam_step.py`
  - `scripts/validate_benchmark_contract.py`
  - `docs/hi_fidelity_validation_stack.md`
  - `output/blackcat_004/hifi_support_reaction_rerun_20260418/structural_check.json`
  - `output/blackcat_004/hifi_wire_support_cluster_rerun_20260418/structural_check.md`
- Model family: external shell-plus-beam FEM spot-check built from STEP geometry and CalculiX decks.
- Mechanics / assumptions:
  - Gmsh meshes a STEP geometry into an `.inp`.
  - Named `ROOT`, `TIP`, and `WIRE_n` node sets are added for later boundary mapping.
  - CalculiX decks are assembled with simplified isotropic material data and boundary/load cards.
  - The mesh-diagnostic layer classifies failure modes such as duplicate facets, invalid surface elements, and no-volume-element outcomes.
- Load assumptions:
  - Best current compare path replays spatial main/rear `Fz` loads from `spar_data.csv`.
  - This is better than a single tip-load or a collapsed single-node replay, but it is still not a full torque/twist/composite contract.
- Boundary conditions:
  - Root clamp derived from mesh node clusters.
  - Wire support currently applied as one or a few `U3` support nodes or a small support patch.
- Wire / support assumptions:
  - No explicit cable/truss element in the current structural-check route.
  - Support clustering is a practical compare aid, not a final physical wire model.
- Torque / `Cm` assumptions:
  - The route is not yet a full torque-ownership benchmark.
  - Current strongest evidence is mainly deflection and reaction sanity under distributed `Fz`.
- What has parity or compare evidence:
  - Best current representative run:
    - overall comparability `LIMITED`
    - static tip-deflection comparability `COMPARABLE`
    - tip deflection difference `6.72%`
    - support reaction difference `0.00284%`
    - analysis reality `shell_plus_beam`
    - no volume elements present
- What it can be trusted for:
  - Local structural spot-check of load mapping, support mapping, and order-of-magnitude stiffness.
  - Detecting mesh-contract failures and support-mapping mistakes.
- What it cannot be trusted for:
  - Final external truth for beam calibration.
  - Final composite section truth.
  - Final torque or shell-hotspot sign-off.
  - A clean canonical benchmark until the beam-only ladder is done first.

## 8. Existing validation docs and tests

- Main docs:
  - `docs/ansys_equivalent_beam_validation_pass.md`
  - `docs/dual_spar_spotcheck_workflow.md`
  - `docs/hi_fidelity_validation_stack.md`
  - `docs/direct_dual_beam_v1_research.md`
  - `docs/dual_beam_v2_mainline_spec.md`
  - `docs/dual_beam_workflow_architecture_overview.md`
- Main regression / contract tests:
  - `tests/test_ansys_crossval.py`
  - `tests/test_ansys_dual_spar_spotcheck.py`
  - `tests/test_ansys_dual_beam_production_check.py`
  - `tests/test_ansys_export.py`
  - `tests/test_dual_beam_mainline.py`
  - `tests/test_internal_dual_beam_regression.py`
  - `tests/test_inverse_design.py`
  - `tests/test_hifi_calculix_runner.py`
  - `tests/test_hifi_gmsh_runner.py`
  - `tests/test_hifi_structural_check.py`
  - `tests/test_phase13_moment_ownership_ab_test.py`
- Interpretation:
  - These tests are valuable for freezing semantics, interfaces, and compare helpers.
  - They do not replace an apples-to-apples structural benchmark ladder.
  - In particular, passing a test that freezes `dual_beam_production` ownership or exporter formatting does not by itself prove the model form is physically validated.

## Inventory Conclusions

- The repo already contains enough structural machinery to build a serious benchmark ladder. The missing piece is not code volume; it is benchmark discipline.
- The cleanest already-proven external validation route is still the legacy equivalent-beam parity case.
- The cleanest already-proven explicit two-beam parity case is the internal-dual-beam versus dual-spar ANSYS smoke.
- The current production route is physically richer than both, but that extra richness is exactly why it still needs its own controlled external validation ladder before any calibration factor is allowed near production equations.
