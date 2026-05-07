# Phase 9 Structure/Jig Model Callgraph

## Verdict

The Phase 9 and smooth production baseline validation structure results did **not** use the real dual-beam production jig-shape path. They used a concept-stage structure/jig proxy owned by `scripts/phase9_structure_jig_smooth_planform.py`, with AVL spanload integrals, a scalar wire-relieved tip-deflection estimate, and a carbon tube catalog EI/mass screen.

The real dual-beam / inverse-jig modules exist under `src/hpa_mdo/structure/dual_beam_mainline/` and `src/hpa_mdo/structure/inverse_design.py`, and are exercised by `scripts/direct_dual_beam_inverse_design.py`, but the Phase 9 and smooth baseline validation scripts never call them.

## Phase 9 Call Path

Primary script:

- `scripts/phase9_structure_jig_smooth_planform.py`

Structure/jig chain:

1. `run_phase9()` at `scripts/phase9_structure_jig_smooth_planform.py:1238`
2. `run_avl_variant()` at `scripts/phase9_structure_jig_smooth_planform.py:920`
3. `scripts.audit_avl_induced_drag_credibility.run_avl_trim_and_spanload()` at `scripts/audit_avl_induced_drag_credibility.py:464`
4. `hpa_mdo.aero.avl_spanwise.build_spanwise_load_from_avl_strip_forces()` via `scripts/audit_avl_induced_drag_credibility.py:491`
5. `spanload_structure_metrics()` at `scripts/phase9_structure_jig_smooth_planform.py:721`
6. `structure_jig_row()` at `scripts/phase9_structure_jig_smooth_planform.py:777`
7. `nominal_jig_estimate()` at `scripts/phase9_structure_jig_smooth_planform.py:745`
8. `hpa_mdo.concept.jig_shape.estimate_tip_deflection()` at `src/hpa_mdo/concept/jig_shape.py:28`
9. `tube_ei_nm2()` at `scripts/phase9_structure_jig_smooth_planform.py:843`
10. `required_ei_from_deflection()` at `scripts/phase9_structure_jig_smooth_planform.py:909`
11. `carbon_tube_candidates()` at `scripts/phase9_structure_jig_smooth_planform.py:860`

Phase 9 writes:

- `output/phase9_structure_jig_smooth_planform/structure_jig_comparison.csv`
- `output/phase9_structure_jig_smooth_planform/carbon_tube_mass_estimate.csv`

## Smooth Baseline Validation Call Path

Primary script:

- `scripts/validate_smooth_tier2_production_baseline.py`

Structure/jig chain:

1. `run_validation()` at `scripts/validate_smooth_tier2_production_baseline.py:788`
2. `run_avl_aero_summary()` at `scripts/validate_smooth_tier2_production_baseline.py:322`
3. `scripts.audit_avl_induced_drag_credibility.run_avl_trim_and_spanload()` at `scripts/audit_avl_induced_drag_credibility.py:464`
4. `structure_jig_audit()` at `scripts/validate_smooth_tier2_production_baseline.py:551`
5. `old_fx_raw_structure_metrics()` at `scripts/validate_smooth_tier2_production_baseline.py:525`
6. `phase9.spanload_structure_metrics()` at `scripts/phase9_structure_jig_smooth_planform.py:721`
7. `phase9.structure_jig_row()` at `scripts/phase9_structure_jig_smooth_planform.py:777`
8. `phase9.nominal_jig_estimate()` at `scripts/phase9_structure_jig_smooth_planform.py:745`
9. `hpa_mdo.concept.jig_shape.estimate_tip_deflection()` at `src/hpa_mdo/concept/jig_shape.py:28`
10. `phase9.tube_ei_nm2()` at `scripts/phase9_structure_jig_smooth_planform.py:843`
11. `phase9.required_ei_from_deflection()` at `scripts/phase9_structure_jig_smooth_planform.py:909`
12. `phase9.carbon_tube_candidates()` at `scripts/phase9_structure_jig_smooth_planform.py:860`
13. `structure_feasibility_status()` at `scripts/validate_smooth_tier2_production_baseline.py:495`

Smooth baseline validation writes:

- `output/final_candidate_validation/smooth_tier2_production_baseline/structure_jig_audit.csv`
- `output/final_candidate_validation/smooth_tier2_production_baseline/carbon_tube_catalog_selection.csv`

## Feature Usage Matrix

| Item | Phase 9 / smooth validation use? | Evidence |
|---|---:|---|
| `estimate_tip_deflection` | Yes | Imported at `scripts/phase9_structure_jig_smooth_planform.py:30`; called by `nominal_jig_estimate()` at lines `757-762`. |
| Jig-shape proxy | Yes | `structure_jig_row()` subtracts scalar deflection from loaded tip z at lines `801-803`. |
| Carbon tube catalog proxy | Yes | `carbon_tube_candidates()` reads `data/carbon_tubes.csv` and computes EI/mass at lines `860-906`. |
| Root bending proxy | Yes | `spanload_structure_metrics()` integrates `y * lift_per_span` at lines `726-739`. |
| Single equivalent beam | Yes, effectively | `estimate_tip_deflection()` uses one per-wing aggregate EI and a cantilever formula at `src/hpa_mdo/concept/jig_shape.py:61-84`. |
| Dual-beam model | No | No call to `hpa_mdo.structure.dual_beam_mainline.*` exists in the Phase 9 or smooth validation structure path. |
| Tension-only wire model | No | Phase 9 uses a prescribed relief fraction, not the truss wire solver. |
| Wire pretension | No | No wire unstretched/reference length or pretension input appears in the Phase 9 path. |
| Deformed-axis / loaded-shape recovery | No | Only scalar tip deflection is applied; no nodewise loaded-shape recovery is called. |
| Jig-shape inverse solver | No | No call to `build_frozen_load_inverse_design*()` or `predict_loaded_shape()` from the Phase 9 path. |

## Real Dual-Beam Path That Exists But Was Not Used

The real structure path exists here:

- `src/hpa_mdo/structure/dual_beam_mainline/types.py`
  - `AnalysisModeName.DUAL_BEAM_PRODUCTION` at lines `11-17`
  - `WireBCMode.WIRE_MAIN_TRUSS` at lines `27-32`
  - `DualBeamMainlineModel` fields at lines `105-172`
- `src/hpa_mdo/structure/dual_beam_mainline/api.py`
  - `run_dual_beam_mainline_kernel()` at lines `65-147`
  - `run_dual_beam_mainline_analysis()` at lines `150-181`
- `src/hpa_mdo/structure/dual_beam_mainline/solver.py`
  - `_evaluate_explicit_wire_truss_support()` at lines `127-225`
  - `solve_dual_beam_state()` nonlinear wire branch at lines `279-390`
- `src/hpa_mdo/structure/inverse_design.py`
  - `predict_loaded_shape()` at lines `263-277`
  - `build_frozen_load_inverse_design()` at lines `569-696`
  - `build_frozen_load_inverse_design_from_mainline()` at lines `699-746`
- `scripts/direct_dual_beam_inverse_design.py`
  - builds a `DualBeamMainlineModel` and runs `run_dual_beam_mainline_kernel(mode=DUAL_BEAM_PRODUCTION)` at lines `2397-2407`
  - calls `build_frozen_load_inverse_design_from_mainline()` at lines `2410-2428`
  - stores dual-beam mass, tip deflection, loaded-shape error, jig clearance, prebend, and curvature at lines `2478-2555`
