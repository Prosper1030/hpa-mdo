# Pathfinder Basis Lock - current_avl_compromise_conservative_closed

> Date: 2026-05-09
> Candidate: `current_avl_compromise_conservative_closed`
> Evidence rule: use commit history, current reports, and actual artifacts. Do
> not use old README narrative as primary evidence.

## Executive Lock

`current_avl_compromise_conservative_closed` is locked as the current
production-facing pathfinder for downstream engineering review, but only as a
`screening_closed_compromise_candidate`.

The locked downstream basis starts cleanly at
`smooth_tier2_production_baseline` and proceeds through candidate-owned AVL
loads, structure-budgeted loaded-Z search, loaded-shape AVL recheck, Tier2
full-alpha airfoil selection, and aero-structure closure.

The upstream mission/Fourier tooling is real in commit history, but there is no
single promoted current trace manifest proving that the current mission handoff
was carried through Fourier/Fourier-AVL candidate generation into this go-mode
candidate. Therefore the pathfinder is a valid downstream screening surrogate,
not a final end-to-end mission-derived aircraft.

## Commit Evidence Pins

| scope | commit evidence | read |
|---|---|---|
| Mission and pilot-power source line | `72754501`, `addfa714`, `6e42891b`, `a32c2078`, `ba7c964d` | Current mission design-space and thermal/pilot-power machinery exists. |
| MissionContract / FourierTarget / sidecar language | `55cc75e9`, `e34a6655`, `9eff6f88`, `7e319f5f`, `f9600bac`, `08f32ae4`, `07a7157f` | The upper pipeline vocabulary exists, but not as one promoted current candidate trace. |
| Fourier-AVL calibration | `2711572a`; hardened by `3e4c55c5` | Tool exists; committed calibration rows are legacy medium-search diagnostics unless explicitly rebuilt. |
| Smooth production baseline | `2796eb8b` | Downstream geometry/AVL carrier exists. |
| Loaded-shape AVL and closure MVPs | `f0dabdcf`, `c686e71d` | Downstream loaded-Z, loaded-shape AVL, airfoil, and closure loop exist. |
| Go-mode candidate package | `8e014521` | Final candidate package and geometry exports are committed. |
| Structural guardrails after package | `65d39bd7`, `3f95dbf6`, `5580f35f`, current `HEAD=3e4c55c5` | Later work tightens FEM/detail claim boundaries; it does not promote final aircraft signoff. |

## Locked Candidate Metrics

Primary evidence:

- `output/go_mode_main_wing_candidate/final_candidate_package/GO_MODE_DECISION.md`
- `output/go_mode_main_wing_candidate/final_candidate_package/candidate_summary.csv`
- `output/go_mode_main_wing_candidate/final_candidate_package/artifact_manifest.json`

Selected row:

| item | value |
|---|---:|
| selected role | `conservative_best` |
| assignment | `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g05_child_0032_70ef8136` |
| airfoil query quality | `actual_loaded_shape_query_pass` |
| closure status | `closed_for_screening` |
| structure trust | `daily_screening_not_final_truth` |
| P crank | `174.600 W` |
| conservative P crank | `178.882 W` |
| CL | `1.16853` |
| CDi | `0.0127613` |
| e_CDi | `0.9564` |
| profile CD | `0.00936885` |
| CD0 total | `0.01325873` |
| tube mass | `10.8736 kg` |
| total structural mass | `13.3736 kg` |
| jig ground clearance | `42.39 mm` |
| wire tension | `3024 N` |
| equivalent tip deflection | `1.543 m` |
| target main tip Z | `2.700 m` |
| beam-line effective dihedral proxy | `8.9386 deg` |

Engineering read: the numbers are good enough to continue focused engineering
review, but not comfortable enough for production release. `42.39 mm`
clearance is thin for build tolerance, runway variation, joint compliance, and
wire setup. `1.543 m` equivalent tip deflection and `3024 N` wire tension still
need coupled structural/aeroelastic and hardware-load-path review.

## Artifact Chain

| stage | input basis | output artifact | trust | gap |
|---|---|---|---|---|
| Mission contract | `configs/mission_design_space_example.yaml`; `data/pilot_power_curves/current_pilot_power_curve.csv`; `data/pilot_power_curves/current_pilot_power_curve.metadata.yaml`; `scripts/mission_design_space_explorer.py` | Local current artifacts exist under `output/mission_design_space/`, including `summary.json` and `optimizer_handoff.json`. Current local summary reports `22464` cases and `1047` robust cases. | `current_source_plus_local_actual_artifact` | `output/mission_design_space/` is ignored output, not a committed promoted trace into this candidate. |
| MissionContract / FourierTarget | `src/hpa_mdo/mission/contract.py`; `src/hpa_mdo/aero/fourier_target.py`; `scripts/birdman_spanload_design_smoke.py`; `docs/mission_drag_budget.md` | Sidecar vocabulary for `mission_contract.*` and `fourier_target.*` bundles. | `implemented_shadow_contract` | Shadow language exists, but no committed current Stage-0-to-go-mode manifest. |
| Fourier-AVL calibration | `scripts/fourier_avl_calibration_mvp.py` | `output/pipeline_redesign_v2/fourier_avl_calibration_mvp/recommended_fourier_bridge.md`; `fourier_command_to_avl_realized.csv` | `reusable_tool_with_legacy_committed_output` | The committed rows point to `output/birdman_mission_coupled_medium_search_20260503/...`, so they are legacy diagnostics, not current pathfinder evidence. |
| Fourier spanload candidate generation | `scripts/birdman_mission_coupled_spanload_search.py`; `scripts/birdman_spanload_design_smoke.py` | Generated sidecar candidate exports and pipeline-v2 docs. | `implemented_but_not_promoted_current_trace` | No clean current trace from mission seed to this go-mode candidate. |
| Smooth production geometry realization | `output/final_candidate_validation/smooth_tier2_production_baseline/validation_manifest.json`; `aerodynamic_summary.md`; geometry exports | Smooth planform/AVL carrier; original smooth baseline assignment used `tip:cst_tip_nsga2_g06_child_0056_b3f9b7c4`. | `current_screening_carrier` | It is the credible downstream starting point, not proven current Stage-2 mission output. Later conservative closed airfoil assignment changes the tip to `g05_child_0032_70ef8136`. |
| AVL realization check | `output/final_candidate_validation/smooth_tier2_production_baseline/avl_runs/...`; `output/phase10_2_canonical_inverse_design_check/smooth_tier2_candidate_avl_spanwise_loads.json` | Candidate-owned AVL geometry, trim, strip-force, and spanwise-load artifacts. | `current_screening` | Load ownership is usable for downstream screening, but not a final coupled aeroelastic load. |
| Structure-budgeted loaded-Z search | `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary/smooth_tier2_canonical_config.yaml`; candidate AVL artifacts; `output/blackcat_004/ansys/crossval_report.txt` | `recommended_loaded_z_states.md`; `z_state_structure_budget_sweep.csv`; selected run `runs/target_main_tip_z_2p700m/` | `current_screening` | Z is a main/rear spar beam-line proxy. The CSV still carries `aero_surface_z_m=1.050581644` with source `baseline_smooth_section_table_not_remapped_for_scaled_beam_line_target`. |
| Loaded-shape AVL recheck | Selected loaded-shape spar CSV from the `2p700m` run | `current_avl_compromise_conservative_closed_loaded_shape_avl_recheck/loaded_shape_aero_recheck_report.md`; `loaded_shape_avl_recheck.csv`; `runs/target_main_tip_z_2p700m/loaded_shape_wing.avl` | `current_screening_with_aero_warning` | Recheck explicitly says `beam_line_z_proxy_not_aero_surface_truth`; diagnostic stall margin is negative but not a gate. |
| Tier2 full-alpha airfoil selection | Loaded-shape local `Cl/Re`; reusable Tier2 airfoil DB | `current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_airfoil_report.md`; `tier2_loaded_shape_selected_avl_recheck.csv` | `current_screening` | Trust is only as good as the loaded-shape `Cl/Re` proxy. Raw best is rejected; only `conservative_best` is promotable. |
| Aero-structure closure | Selected airfoil AVL rerun plus structure response | `current_avl_compromise_conservative_closed_closure/aero_structure_closure_report.md`; `aero_structure_closure_summary.csv`; final candidate package | `current_screening_closed` | `closed_for_screening` is daily screening closure, not final structural/aeroelastic truth. |
| FEM/APDL / shell / load-factor guardrails | Final candidate package and structural response | Phase 15/16/17/21/30/32/37/47 style reports | `spot_check_guardrail` | They identify blockers and conditional checks. They do not close rear spar, rib load transfer, root fitting, wire attach, termination, or full-wing global buckling signoff. |

## Geometry State Consistency Lock

Short answer: the downstream chain is internally consistent only if it is read as
a root-offset-removed beam-line loaded-Z proxy. It is not yet a fully physical
aerodynamic-surface / clearance / quarter-chord geometry lock.

| quantity | evidence | value / state | basis read |
|---|---|---:|---|
| Absolute main beam loaded-Z | `z_state_structure_budget_sweep.csv`; selected `target_main_tip_z_2p700m` | `2.700000 m` | Structural main-beam target and loaded shape. |
| Absolute rear beam loaded-Z | same row | `2.684757 m` | Structural rear-beam target and loaded shape. |
| Main beam root offset | same row | `0.071439 m` | Structural beam-line root Z, not aerodynamic root. |
| AVL/VSP loaded section tip Z | `final_candidate_package/geometry_exports/.../geometry_manifest.json`; `section_table.csv` | `2.628560870 m` | This equals `2.700000 - 0.071439` within numerical noise, so final AVL/VSP export is tied to the selected beam-line state after root-offset removal. |
| Baseline aerodynamic surface Z | `z_definition_audit.md`; `z_state_structure_budget_sweep.csv` | `1.050581644 m` | Baseline smooth section-table tip Z, explicitly not remapped for the scaled beam-line target. |
| Clearance | `validity_summary.json`; `candidate_summary.csv` | `0.042389758 m` | Minimum structural/jig beam-node Z margin above floor, driven by rear beam; not yet a skin/quarter-chord/whole-aircraft ground-clearance statement. |
| Loaded-shape AVL basis | `loaded_shape_aero_recheck_report.md` | `main_beam_loaded_shape_spar_data_root_offset_removed_as_avl_section_z_proxy` | Screening proxy for aero consequences, not final aerodynamic-surface truth. |

Implications:

- Beam-line proxy, loaded-shape AVL, Tier2 airfoil selection, final geometry
  export, and closure are talking about the same selected beam-line proxy after
  root-offset removal.
- The final package's `loaded_tip_z_m = 2.628560870` is not a contradiction of
  the Z-search `target_main_tip_z_m = 2.700000`; it is the same main-beam tip
  state after subtracting the structural root offset.
- The currently reported `aero_surface_z_m = 1.050581644` is still the baseline
  smooth geometry reference and should not be mixed with the high-Z loaded
  proxy as if both were final aerodynamic surface definitions.
- Clearance rejects the low-Z samples robustly under the current beam-line
  model, but it does not yet prove full physical ground clearance of the
  aerodynamic surface, skin thickness, wheels/support state, runway tolerance,
  or assembled hardware.

Low-Z evidence:

| sampled state | mass read | clearance read | result |
|---|---:|---:|---|
| `6.0 deg / 1.804 m` | `16.482 kg` total structural mass | `-116.2 mm` | not promotable: mass budget and clearance fail under current model |
| `6.5 deg / 1.956 m` | `16.482 kg` total structural mass | `-32.5 mm` | not promotable: mass budget and clearance fail under current model |
| `7.0 deg / 2.108 m` | `14.426 kg` total structural mass | `-86.8 mm` | not promotable: clearance fails under current model |
| `8.939 deg / 2.700 m` | `13.374 kg` total structural mass | `42.4 mm` | first sampled compromise pass in this package |

## Closure Read

The conservative row is meaningfully closed for screening:

- loaded-shape AVL recheck: `CDi = 0.0127613`, `e_CDi = 0.9564`
- closure deltas for `conservative_best`: `0.0%` e_CDi, spanload, mass, and
  deflection deltas
- closure clearance remains `0.042389758 m`
- query quality is `actual_loaded_shape_query_pass`

The raw row is not promotable:

- `loop_back_to_airfoil_selection`
- `actual_loaded_shape_query_warning_not_mission_grade`
- `P_crank = 276.104 W`, conservative `281.456 W`
- spanload and induced-drag deltas are large enough to treat it as diagnostic.

Engineering caution: zero closure delta here means the selected conservative
airfoil rerun and structure response agree on the same screening proxy state.
It does not mean the aircraft is physically signed off.

## Priority Decision

Among ASWing coupling, rib sensitivity, and FEM detail, do bounded rib/rear-spar
sensitivity first.

Reason:

1. Existing current reports already show that rear-spar/rib assumptions move the
   structural response strongly: Phase32 records `rear_stiffness_5pct` changing
   tip response by about `292.6%` and spar-pair angle by `36.3 deg`, while
   `dense_finite_rib_surrogate` changes tip response by about `-17.7%` and
   spar-pair angle by `-8.34 deg`.
2. ASWing coupling is valuable, but a nonlinear aeroelastic run on the wrong
   structural stiffness basis would only make a cleaner-looking wrong answer.
   The repo has ASWing exporter/runner glue, but no current candidate ASWing
   artifact and no local `aswing` binary found in PATH during this lock pass.
3. FEM detail is important, especially root joint, wire termination, wire attach,
   and rib hardware. But detail FEM should consume a locked load/geometry state;
   it should not decide which beam-line/aero-surface state is real.

Recommended sequence:

1. **Bounded rib/rear-spar sensitivity on the locked pathfinder**: run nominal,
   rear-soft/rear-stiff, finite-rib-link, and no-rib/limited-rib variants on the
   exact `current_avl_compromise_conservative_closed` load and Z basis. Output
   must report loaded tip Z, root-offset-removed AVL section Z, clearance,
   equivalent twist, tube mass, wire tension, and whether closure ranking would
   change.
2. **ASWing coupling after the sensitivity envelope exists**: export the
   pathfinder plus the sensitivity envelope to ASWing or an equivalent
   aeroelastic loop, then check whether trim, twist, load redistribution, and
   loaded surface Z still support the same candidate.
3. **FEM detail after the coupled basis is stable**: root fitting, wire attach,
   termination, rib/spar attach, and full-wing global buckling should then be
   sized against the locked load envelope, not against a single unchallenged
   beam-line proxy.

## Basis Lock Verdict

Proceed with the candidate, but keep the claim narrow:

```text
current_avl_compromise_conservative_closed
= downstream screening pathfinder locked from smooth_tier2_production_baseline
  through loaded-Z, loaded-shape AVL, Tier2 airfoil, and closure.

Not locked yet:
current mission -> promoted Fourier/Fourier-AVL trace -> this exact candidate,
and physical aerodynamic surface / quarter-chord / clearance equivalence.
```
