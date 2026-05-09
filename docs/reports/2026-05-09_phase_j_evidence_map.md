# Phase J Evidence Map

> Status: deep refresh after source-contamination audit on 2026-05-09.
> Canonical use: read this with `CURRENT_MAINLINE.md` and
> `docs/reports/2026-05-08_commit_history_report.md`.
> Hard rule: do not use old medium-search artifacts as current Phase J upstream
> truth.

## Executive Finding

- The current production-facing review candidate is still
  `current_avl_compromise_conservative_closed`.
- That candidate is only `screening_closed_compromise_candidate` /
  `daily_screening_not_final_truth`.
- The previous evidence map was contaminated by the older
  `output/birdman_mission_coupled_medium_search_20260503` route. The
  `sample_1476`, `233.47 W`, and `8642.9 m` records are not current upstream
  evidence.
- The current mission-side source is the later mission-design-space /
  mission-drag-budget contract line, especially `output/mission_design_space/`
  and `docs/mission_drag_budget.md`.
- The current go-mode candidate is not a fully end-to-end candidate generated
  from the current mission handoff through a clean current Fourier spanload
  generator. It is a downstream screening closure built around the existing
  `smooth_tier2_production_baseline` AVL/geometry carrier.
- Therefore the important unresolved source-chain gap is upstream:
  current mission contract -> current Fourier/Fourier-AVL candidate source ->
  smooth realization. The important geometry gap remains
  beam-line Z proxy -> aerodynamic surface -> clearance.
- Rib / rear-spar / root / wire-detail FEM remains downstream validation unless
  new evidence shows it can reorder the aero-structure closure candidates.

## Actual Pipeline State

### Intended Phase J Pipeline

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
-> FEM/APDL / shell buckling / load-factor checks
```

### Implemented Evidence Chain Today

```text
Mission design-space / drag-budget contract
-> current gap: no clean current mission-to-Fourier-to-candidate source chain
-> existing smooth_tier2_production_baseline geometry and AVL actual loads
-> go-mode structure-budgeted loaded-Z search
-> loaded-shape AVL recheck on beam-line Z proxy
-> Tier2 loaded-shape airfoil selection
-> aero-structure closure
-> candidate FEM/APDL/shell/load-factor spot-checks
```

This means the downstream go-mode chain is useful, but the upstream evidence
chain is not yet closed. The correct interpretation is:

```text
current_avl_compromise_conservative_closed
= production-facing screening candidate for review,
not final mission-derived aircraft truth.
```

## Where The Previous Map Went Wrong

| issue | root cause | affected rows | corrected reading |
|---|---|---|---|
| `233.47 W / 8642.9 m` looked like current evidence | Old `birdman_mission_coupled_medium_search_20260503` was read as if it were current Phase J source truth | Mission contract, Fourier candidate generation | Superseded diagnostic only; do not use for current mission or current candidate |
| `rank_01_sample_1476` looked like current Fourier evidence | `fourier_avl_calibration_mvp` was built from old top-candidate exports | Fourier-AVL calibration | Tool is useful, but current artifact is `diagnostic_legacy` until rebuilt from current mission handoff |
| Stage 2 looked implemented as a current artifact | Pipeline spec says Stage 2 exists, but `output/pipeline_redesign_v2` has no clean current Stage 2 generator output | Fourier spanload candidate generation | Current Stage 2 is a gap, not a validated handoff |
| Downstream closure looked like full aircraft closure | Go-mode package closes the downstream screening loop, but inherits upstream and Z-basis gaps | Smooth geometry onward | Valid screening evidence only, not final design sign-off |

## Stage Evidence Table

| pipeline stage | current evidence | trust level | what it proves | open gap | next action |
|---|---|---|---|---|---|
| Mission contract | `docs/mission_drag_budget.md`; `docs/mission_design_space_explorer.md`; `output/mission_design_space/report.md`; `output/mission_design_space/summary.json`; `output/mission_design_space/optimizer_handoff.json`; `output/mission_design_space/candidate_seed_pool.csv` | `source_contract_screening` | Current mission design-space exists: target range `42.195 km`, target environment `33 C / 80%RH`, speed grid `5.8-7.0 m/s`, span grid `33-35 m`, AR grid `37-40`, mass grid `96-101 kg`, `1047` robust cases, robust speed envelope `[6.1, 7.0] m/s`, `624` seed rows. | This is search-bound / pre-gate evidence, not a promoted aircraft geometry. It does not prove the go-mode candidate satisfies the full mission. | Keep it as Stage 0 source. Rebuild downstream source chain from `optimizer_handoff.json` instead of old medium-search output. |
| MissionContract / FourierTarget shadow layer | `docs/mission_drag_budget.md`; `src/hpa_mdo/mission/contract.py`; `src/hpa_mdo/aero/fourier_target.py`; `scripts/birdman_spanload_design_smoke.py` | `shadow_contract` | The repo has a contract adapter and FourierTarget language using `CL_req`, `AR`, `span_m`, `speed_mps`, `rho`, and `weight_n`. | The docs explicitly say shadow mode does not change ranking, objective, hard gates, or rejection behavior. | Promote only after a deliberate current run ties mission seed rows to candidate geometry and output bundles. |
| Fourier-AVL calibration | `output/pipeline_redesign_v2/fourier_avl_calibration_mvp/recommended_fourier_bridge.md`; `output/pipeline_redesign_v2/fourier_avl_calibration_mvp/fourier_command_to_avl_realized.csv` | `diagnostic_legacy` | The calibration tool and output format exist. The sampled rows show `outer_underloaded_authority_limited`, `target_vs_avl_rms = 0.178-0.216`, `outer_delta = 0.241-0.306`, `e_fourier_realized = 0.846-0.873`, and `e_avl_cdi = 0.851-0.870`. | The actual CSV source paths are old `birdman_mission_coupled_medium_search_20260503/top_candidate_exports/rank_*` records. This is not current mission evidence. | Re-run or re-map Fourier-AVL calibration on current mission design-space / smooth/go-mode candidate artifacts. Until then, do not use this row to rank current candidates. |
| Fourier spanload candidate generation | No clean current Phase J Stage 2 artifact found under `output/pipeline_redesign_v2/` or `output/go_mode_main_wing_candidate/`. Superseded source quarantined: `output/birdman_mission_coupled_medium_search_20260503/`. | `missing_current_evidence` | The pipeline spec defines the stage, but current repo artifacts do not show a current mission-handoff-derived Stage 2 candidate generator result. | This is the main upstream break. The go-mode candidate cannot be claimed as mission -> Fourier -> smooth end-to-end truth. | Build a current Stage 2 handoff from mission seed rows and calibrated AVL actual-load evidence, or explicitly document that the current candidate starts from existing smooth baseline evidence. |
| Smooth production geometry realization | `output/final_candidate_validation/smooth_tier2_production_baseline/validation_manifest.json`; `output/final_candidate_validation/smooth_tier2_production_baseline/aerodynamic_summary.md`; `output/phase9_structure_jig_smooth_planform/recommended_candidate.md` | `current_screening` | Smooth production geometry exists. Candidate: `smooth_tier2_production_baseline`, assignment `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g06_child_0056_b3f9b7c4`, `P_crank = 171.160 W`, `P_crank_conservative = 175.291 W`, `CDi = 0.012501`, `profile_cd = 0.009510`, `target_vs_avl_rms = 0.0292`, `outer_delta = 0.0885`. | This baseline explicitly failed structure/jig proxy and was not final structure truth. It is also not proven to come from current Stage 2 mission/Fourier source. | Keep as the current geometry/AVL carrier for downstream screening while rebuilding upstream traceability. |
| AVL realization check | `output/final_candidate_validation/smooth_tier2_production_baseline/aerodynamic_summary.md`; `output/phase10_2_canonical_inverse_design_check/smooth_tier2_candidate_avl_spanwise_loads.json`; candidate-owned AVL artifacts referenced by Z search contracts | `current_screening` | Candidate-owned AVL geometry, trim, strip-force, and spanwise-load artifacts exist and feed downstream structure-budgeted search. | Load ownership is good enough for screening, but mission/Fourier origin is not closed. | Preserve AVL actual spanload as the downstream aero owner. Do not replace it with raw commanded Fourier coefficients. |
| Structure-budgeted loaded-Z search | `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary/recommended_loaded_z_states.md`; `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary/z_state_structure_budget_sweep.csv` | `current_screening` | Selected row `target_main_tip_z_2p700m`: main tip Z `2.700 m`, rear tip Z `2.684757 m`, beam-line effective dihedral proxy `8.938613 deg`, tube mass `10.873637 kg`, total structural mass `13.373637 kg`, clearance `42.39 mm`, wire tension about `3024 N`. Low-Z samples fail: `6.0 deg / 1.804 m` mass+clearance, `6.5 deg / 1.956 m` mass+clearance, `7.0 deg / 2.108 m` clearance. | Z is still a spar beam-line proxy, not aerodynamic-surface truth. | Next physical task is beam-line / aerodynamic surface / clearance alignment. |
| AVL recheck on realizable loaded shape | `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_loaded_shape_avl_recheck/loaded_shape_aero_recheck_report.md`; `loaded_shape_avl_recheck.csv` | `current_screening` | Recheck exists for `2.700`, `2.725`, and `2.750 m`. Selected row keeps `CDi = 0.012761`, `e_CDi = 0.9564`, `max Cl = 1.341`, `Re min = 291577`, and carries `beam_line_z_proxy_not_aero_surface_truth`. | Negative diagnostic stall margin is a warning, not a gate. Z transfer still uses main-beam loaded shape as AVL section-Z proxy. | Use this only as screening input to airfoil selection. |
| Tier2 full-alpha airfoil selection | `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_airfoil_report.md`; `tier2_loaded_shape_selected_avl_recheck.csv` | `current_screening` | Loaded-shape `Cl/Re` based Tier2 selection exists. `conservative_best` is `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g05_child_0032_70ef8136`, `profile_cd = 0.009369`, `CD0_total = 0.013259`, `P_crank = 174.60 W`, `P_crank_cons = 178.88 W`, `stall margin = 1.589`, query quality `actual_loaded_shape_query_pass`. `raw_best` is rejected with query warning and `P_crank = 276.10 W`. | Only as trustworthy as the loaded-shape `Cl/Re` basis. | Keep raw/conservative split. Carry only `conservative_best` into closure. |
| Aero-structure closure | `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_closure/aero_structure_closure_report.md`; `aero_structure_closure_summary.csv`; `output/go_mode_main_wing_candidate/final_candidate_package/GO_MODE_DECISION.md`; `artifact_manifest.json`; `candidate_summary.csv` | `current_screening_closed` | `current_avl_compromise_conservative_closed` is the single production-facing screening candidate. `conservative_best` has `closed_for_screening`, `P_crank = 174.600 W`, conservative `178.882 W`, `e_CDi = 0.9564`, total structural mass `13.3736 kg`, clearance `42.39 mm`, wire `3024 N`, tip deflection `1.543 m`, beam-line proxy `8.939 deg`. | This is not final production truth and does not replace production ranking. It inherits upstream Stage 1/2 traceability gap and beam-line Z proxy gap. | Use for manual geometry inspection and FEM/APDL spot-check only. |
| FEM/APDL / shell buckling / load-factor checks | `output/go_mode_fem_validation_repair/phase14_maclocal/maclocal_fem_fidelity_ladder/final_report.md`; `output/phase15_candidate_load_factor_buckling_check/candidate_limit_load_recommendation.md`; `output/phase16_ccx_buckling_wire6_ramp/wire6_load_factor_ramp_report.md`; `output/phase17_candidate_shell_buckling_tip_review/candidate_shell_buckling_report.md` | `spot_check_guardrail` | Phase 14 shell diagnostic passes B2/B5 ladder (`2.410%` B2 shell vs internal beam, `0.070%` B5 torsion vs closed form) but still needs APDL. Phase 15 recommends `1.75G` internal fixed-design boundary only. Phase 16 with 6 kN wire shifts first limiter to tip deflection around `n = 3.305`, wire allowable around `n = 3.968`. Phase 17 local wall coupon clears conditionally, but isolated main-spar shell global mode is about `n = 1.404G`. | Not final aircraft sign-off. Missing rear spar, rib load transfer, root fitting, wire attach, termination, local composite orthotropy, and external APDL confirmation. | Keep as downstream validation queue. Do not let local coupon pass become full-wing buckling pass. |

## Quarantined Or Legacy Sources

Do not use these as current Phase J source truth:

- `output/birdman_mission_coupled_medium_search_20260503/`
- `output/birdman_mission_coupled_*_20260503/`
- `rank_01_sample_1476` and related top-ten medium-search exports
- `233.47 W` / `8642.9 m` medium-search records
- `output/pipeline_redesign_v2/fourier_avl_calibration_mvp/*` as current
  candidate ranking evidence

They may still be useful as historical diagnostics or examples of tool output
format, but they must be labeled `legacy_diagnostic` or
`invalid_for_current_phase_j` when used.

## Engineering Judgement

1. The current lower pipeline is meaningful: smooth geometry, AVL actual loads,
   loaded-Z search, loaded-shape AVL recheck, Tier2 airfoil selection, closure,
   and structural spot-checks form a usable screening chain.
2. The current upper pipeline is not yet clean: current mission design-space
   evidence has not been traced through a current Fourier spanload generator
   into the go-mode candidate.
3. The next short-line task should not be rib FEM. It should first decide
   whether to rebuild the upstream mission/Fourier candidate chain or to
   explicitly declare the current go-mode candidate as a lower-pipeline
   screening surrogate.
4. After that source-chain decision, the most important physical ambiguity is
   still beam-line Z proxy versus aerodynamic surface and clearance.
5. Rib / rear spar / joint / wire detail work remains important for final
   validation, but it should move upstream only if it can change candidate
   ordering or closure status.

## Recommended Immediate Order

1. Rebuild the Stage 0-2 evidence chain from current mission design-space /
   drag-budget sources, or write an explicit waiver that the current go-mode
   candidate begins at `smooth_tier2_production_baseline`.
2. Align beam-line Z, aerodynamic surface Z, dihedral language, and clearance
   for `current_avl_compromise_conservative_closed`.
3. Recheck whether the aligned geometry changes closure metrics or candidate
   ordering.
4. Only then decide whether rib / bracing sensitivity belongs in candidate
   selection or remains downstream FEM/detail validation.
