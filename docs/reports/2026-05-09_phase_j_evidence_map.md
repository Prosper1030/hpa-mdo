# Phase J Evidence Map

> Status: commit-first refresh after source-contamination audit on 2026-05-09.
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
- The mission-to-airfoil design line does exist in commit history. It includes
  current pilot power CSV input, thermal derating, prop/drivetrain efficiency,
  mission design-space scanning, drag-budget contracts, MissionContract /
  FourierTarget adapters, airfoil profile/zone sidecars, CST/NSGA/full-polar
  airfoil work, smooth production geometry, loaded-Z search, loaded-shape AVL
  recheck, Tier2 airfoil selection, and aero-structure closure.
- The corrected unresolved gap is narrower: the repo does not yet have one
  promoted, committed trace manifest proving that the current Stage-0 mission
  handoff was carried through the current Fourier/spanload generator into
  `current_avl_compromise_conservative_closed` without shadow/legacy/diagnostic
  boundaries.
- Therefore `current_avl_compromise_conservative_closed` is a valid
  production-facing screening candidate, but not a final end-to-end
  mission-derived aircraft. The important geometry gap remains beam-line Z
  proxy -> aerodynamic surface -> clearance.
- The intended operating model is pathfinder-first: use one credible candidate
  to close the complete engineering chain, expose blockers, and then widen the
  search space. Do not treat that candidate as a global optimum or a hard gate.
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
Mission design-space / drag-budget contract and reproducible Stage-0 scanner
-> MissionContract / FourierTarget / profile-drag / airfoil sidecar language
-> promotion gap: no single committed current trace manifest to go-mode candidate
-> existing smooth_tier2_production_baseline geometry and AVL actual loads
-> go-mode structure-budgeted loaded-Z search
-> loaded-shape AVL recheck on beam-line Z proxy
-> Tier2 loaded-shape airfoil selection
-> aero-structure closure
-> candidate FEM/APDL/shell/load-factor spot-checks
```

This means the upper pipeline is real, but its current outputs are split across
implemented code, shadow diagnostics, generated/ignored bundles, and downstream
candidate packages. The correct interpretation is:

```text
current_avl_compromise_conservative_closed
= production-facing pathfinder / screening candidate for review,
not final mission-derived aircraft truth.
```

## Pathfinder / Expansion Protocol

The current workflow should be read as:

```text
single credible pathfinder candidate
-> close mission / Fourier / AVL / geometry / loaded-Z / airfoil / structure basis
-> repair local physics and data-contract blockers
-> expand search space only after the closed loop is coherent
```

This protocol matters because the repo contains many useful but old experiments.
A reusable module can be kept, but its output is not current evidence until it is
rerun under the current pathfinder contract.

| class | meaning | allowed current-mainline use |
|---|---|---|
| `current_pathfinder_evidence` | Artifacts tied to the current candidate/load/geometry/airfoil/structure basis | Can support current screening judgement |
| `reusable_tool` | Code or method that can run on current inputs | Can be used after explicit current input/output trace is produced |
| `legacy_diagnostic` | Old output useful for debugging method behavior | Cannot support current candidate claims |
| `quarantined_source` | Known misleading source for current Phase J interpretation | Blocked unless explicitly opted into as legacy diagnostic |

## Where The Previous Map Went Wrong

| issue | root cause | affected rows | corrected reading |
|---|---|---|---|
| `233.47 W / 8642.9 m` looked like current evidence | Old `birdman_mission_coupled_medium_search_20260503` was read as if it were current Phase J source truth | Mission contract, Fourier candidate generation | Superseded diagnostic only; do not use for current mission or current candidate |
| `rank_01_sample_1476` looked like current Fourier evidence | `fourier_avl_calibration_mvp` was built from old top-candidate exports | Fourier-AVL calibration | Tool is useful, but current artifact is `diagnostic_legacy` until rebuilt from current mission handoff |
| Stage 0-2 was described as too missing | I treated absence of one promoted final trace as if the mission/Fourier/sidecar line itself did not exist | Mission contract through Fourier spanload generation | The line exists; the gap is promotion/traceability into the current go-mode candidate, not basic implementation |
| Stage 2 looked final-current | Pipeline spec and tools exist, but `output/pipeline_redesign_v2` does not contain a clean promoted Stage-2-to-go-mode source trace | Fourier spanload candidate generation | Current Stage 2 is implemented/diagnostic, but not yet a validated promoted handoff |
| Downstream closure looked like full aircraft closure | Go-mode package closes the downstream screening loop, but inherits upstream and Z-basis gaps | Smooth geometry onward | Valid screening evidence only, not final design sign-off |

## Stage Evidence Table

| pipeline stage | current evidence | trust level | what it proves | open gap | next action |
|---|---|---|---|---|---|
| Mission contract | `configs/mission_design_space_example.yaml`; `data/pilot_power_curves/current_pilot_power_curve.csv`; `data/pilot_power_curves/current_pilot_power_curve.metadata.yaml`; `scripts/mission_design_space_explorer.py`; `src/hpa_mdo/mission/design_space.py`; `docs/mission_design_space_explorer.md`; `docs/mission_drag_budget.md` | `reproducible_stage0_contract` | Current mission design-space source exists: target range `42.195 km`, target environment `33 C / 80%RH`, speed grid `5.8-7.0 m/s`, span grid `33-35 m`, AR grid `37-40`, mass grid `96-101 kg`, prop efficiency `0.86`, drivetrain efficiency `0.96`. Dry-run on the committed config reports `22464` cases. Generated local `output/mission_design_space/*` currently shows `1047` robust cases and `624` seed rows, but that directory is ignored rather than commit-tracked. | This proves a reproducible Stage-0 search contract and seed handoff language, not a promoted aircraft geometry. It does not by itself prove the go-mode candidate satisfies the full mission. | Keep it as Stage 0 source. Produce a promoted trace bundle from `optimizer_handoff.json` / seed rows into current candidate generation instead of old medium-search output. |
| MissionContract / FourierTarget shadow layer | `docs/mission_drag_budget.md`; `src/hpa_mdo/mission/contract.py`; `src/hpa_mdo/aero/fourier_target.py`; `scripts/birdman_spanload_design_smoke.py` | `implemented_shadow_contract` | The repo has a contract adapter and FourierTarget language using `CL_req`, `AR`, `span_m`, `speed_mps`, `rho`, and `weight_n`. It also writes `mission_contract.*` and `fourier_target.*` bundles in sidecar runs. | The docs explicitly say shadow mode does not change ranking, objective, hard gates, or rejection behavior. | Promote only after a deliberate current run ties mission seed rows to candidate geometry and output bundles. |
| Fourier-AVL calibration | `scripts/fourier_avl_calibration_mvp.py`; `output/pipeline_redesign_v2/fourier_avl_calibration_mvp/recommended_fourier_bridge.md`; `output/pipeline_redesign_v2/fourier_avl_calibration_mvp/fourier_command_to_avl_realized.csv` | `reusable_tool_with_legacy_committed_output` | The calibration tool and output format exist. The sampled committed rows show `outer_underloaded_authority_limited`, `target_vs_avl_rms = 0.178-0.216`, `outer_delta = 0.241-0.306`, `e_fourier_realized = 0.846-0.873`, and `e_avl_cdi = 0.851-0.870`. | The committed CSV source paths are old `birdman_mission_coupled_medium_search_20260503/top_candidate_exports/rank_*` records. This is not current mission evidence. The CLI now requires explicit `--report-json`; old medium-search input is blocked unless `--allow-legacy-medium-search` is passed. | Re-run or re-map Fourier-AVL calibration on current mission design-space / smooth/go-mode candidate artifacts. Until then, do not use the old rows to rank current candidates. |
| Fourier spanload candidate generation | `scripts/birdman_mission_coupled_spanload_search.py`; `scripts/birdman_spanload_design_smoke.py`; `output/airfoil_db/*/sidecar*/top_candidate_exports/*/fourier_target.*` generated bundles; `output/pipeline_redesign_v2/complete_pipeline_v2.md` | `implemented_but_not_promoted_current_trace` | The repo has mission-coupled spanload and FourierTarget machinery. It can create per-candidate Fourier/mission bundles, and later pipeline-v2 docs specify the Stage-2 contract. | The promoted go-mode package does not contain a single clean trace from current Stage-0 seed -> Stage-2 generated candidate -> smooth geometry -> closure. Some generated bundles are ignored output, and some committed calibration rows are legacy diagnostics. | Build a current Stage-2 trace manifest and either connect it to `current_avl_compromise_conservative_closed` or state precisely where the current downstream screening branch begins. |
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
`scripts/fourier_avl_calibration_mvp.py` now enforces this by requiring an
explicit report JSON and by blocking the old medium-search report unless
`--allow-legacy-medium-search` is explicitly passed.

## Engineering Judgement

1. The user's remembered mission-to-airfoil line is real in the repo, not a
   fantasy: current commits contain the mission scanner, pilot power/thermal
   model, drag-budget contract, MissionContract/FourierTarget adapters,
   airfoil sidecars, smooth geometry, loaded-Z search, Tier2 airfoil selection,
   and closure.
2. The current lower pipeline is meaningful: smooth geometry, AVL actual loads,
   loaded-Z search, loaded-shape AVL recheck, Tier2 airfoil selection, closure,
   and structural spot-checks form a usable screening chain.
3. The current upper pipeline is not yet promoted as one clean trace: current
   mission design-space evidence has not been committed as a single
   Stage-0-to-Stage-2-to-go-mode manifest.
4. The next short-line task should not be rib FEM. It should first produce a
   pathfinder promoted trace or explicitly declare where the current go-mode
   candidate begins as a lower-pipeline screening surrogate.
5. After that source-chain decision, the most important physical ambiguity is
   still beam-line Z proxy versus aerodynamic surface and clearance.
6. Rib / rear spar / joint / wire detail work remains important for final
   validation, but it should move upstream only if it can change candidate
   ordering or closure status.

## Recommended Immediate Order

1. Build a promoted Stage 0-2 trace manifest from current mission design-space /
   drag-budget sources, or write an explicit waiver that the current go-mode
   candidate begins at `smooth_tier2_production_baseline`. This is a
   traceability/promotion task, not proof that Stage 0-2 does not exist.
2. Align beam-line Z, aerodynamic surface Z, dihedral language, and clearance
   for `current_avl_compromise_conservative_closed`.
3. Recheck whether the aligned geometry changes closure metrics or candidate
   ordering.
4. Only then decide whether rib / bracing sensitivity belongs in candidate
   selection or remains downstream FEM/detail validation.
