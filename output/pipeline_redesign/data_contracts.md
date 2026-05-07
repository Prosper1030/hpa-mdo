# Data Contracts

## Contract Map

| Contract | Producer | Consumer | Purpose |
|---|---|---|---|
| `MissionContract` | user/config | Fourier, AVL, power model | Defines mass, speed, rho, power and mission objective |
| `FourierTargetContract` | Fourier generator | geometry realizer, AVL compare | Defines desired spanload target |
| `GeometryCandidateContract` | geometry realizer | AVL, structure adapter | Defines planform, chord, twist, provisional Z |
| `AVLRealizationContract` | AVL sidecar | Fourier compare, structure, airfoil | Defines actual spanload, CL/Re, CDi |
| `StructuralBudgetContract` | config/user | Z-state search | Defines mass/jig/wire/manufacturing budget |
| `ZStateSearchContract` | structure wrapper | shortlist, AVL recheck | Defines feasible requested loaded-shape states |
| `Tier2ZoneEnvelopeContract` | AVL loaded-shape recheck | Tier2 DB query | Defines root/mid1/mid2/tip work points |
| `AirfoilComboContract` | Tier2 combo search | AVL rerun, power model | Defines zone assignments and quality |
| `CandidateVerdictContract` | final aggregator | reports / downstream mainline | Defines aero best and production candidate |

## MissionContract

Required fields:

| Field | Meaning |
|---|---|
| `case_id` | unique run/candidate id |
| `mass_kg` | design mass used for CL_req and structure loads |
| `velocity_mps` | cruise speed |
| `rho_kgpm3` | air density |
| `power_available_crank_w` | pilot power budget |
| `crank_to_air_efficiency` | prop/drivetrain estimate |
| `span_bounds_m` | allowed span range |
| `area_bounds_m2` | allowed area range |
| `cl_req_bounds` | allowed cruise CL range |
| `mission_objective` | e.g. fixed_range_best_time |

## FourierTargetContract

Required fields:

| Field | Meaning |
|---|---|
| `fourier_coefficients` | `A1`, `A3`, `A5`, optional higher terms |
| `eta_grid` / `y_m` | span stations |
| `normalized_target_loading` | normalized target `L'(y)` or `cl*c` |
| `target_e_fourier` | idealized induced efficiency |
| `target_outer_loading_ratio` | outer-wing loading metric |
| `local_cl_guard_estimate` | pre-AVL local Cl risk |
| `target_generation_notes` | assumptions and warnings |

Fourier target data must be reportable even when a candidate is rejected, because mismatch diagnosis depends on it.

## GeometryCandidateContract

Required fields:

| Field | Meaning |
|---|---|
| `section_table` | `eta`, `y_m`, `z_m`, `chord_m`, `twist_deg`, `airfoil_placeholder` |
| `planform_quality` | monotonicity, slope jump, curvature proxy, area/MAC error |
| `realization_method` | inverse chord, residual twist, constrained spline, or other |
| `vsp3_path` / `avl_path` | exported geometry paths when available |
| `geometry_manifest` | provenance and limitations |

The section table is the shared boundary between Fourier/AVL/structure/airfoil work.

## AVLRealizationContract

Required fields:

| Field | Meaning |
|---|---|
| `alpha_at_CL_req` | AVL trim angle |
| `CL_req` | required CL |
| `CDi` / `e_CDi` | AVL induced-drag authority |
| `spanload_y_m` | stations for actual loading |
| `Lprime_avl_Npm` | actual lift per span |
| `Cl_avl` / `Re_avl` | actual station work points |
| `target_vs_avl_rms` | Fourier mismatch RMS |
| `target_vs_avl_outer_delta` | outer-wing mismatch |
| `local_cl_utilization` | utilization vs safe Clmax proxy or DB value |
| `avl_contract_sanity` | reference area, paneling, trim, surface selection, symmetry |

When this contract passes sanity, downstream profile drag must use `Cl_avl` and `Re_avl`, not Fourier target Cl.

## StructuralBudgetContract

This is the new early gate.

Required fields:

| Field | Preferred MVP Value | Meaning |
|---|---:|---|
| `spar_tube_mass_target_kg` | 11.5 | target carbon tube mass line |
| `spar_tube_mass_diagnostic_line_kg` | 11.7534 | old reference line for continuity |
| `target_main_tip_z_band_m` | e.g. 2.4..3.2 | requested loaded-shape search band |
| `target_rear_tip_z_policy` | derived from beam geometry | rear beam loaded-Z target |
| `min_jig_clearance_m` | 0.010 preferred, 0.020 robust | ground clearance |
| `max_jig_prebend_m` | config-owned | manufacturing/jig practicality |
| `max_jig_curvature_per_m` | config-owned | smooth jig shape |
| `wire_tension_margin_n` | positive | no overload / adequate margin |
| `wire_slack_allowed` | false | tension-only wire check |
| `moment_closure_required` | true | torque convention must close |
| `loaded_shape_error_tol_m` | config-owned | realizable loaded-shape match |
| `cfrp_precheck_required` | true for finalists | preliminary manufacturability |

Mass definitions must be explicit:

- `spar_tube_mass_kg`: carbon tube mass only.
- `total_structural_mass_kg`: tube plus modeled structural allowances included by the canonical workflow.
- `not_included`: joints, ribs, wires, fittings, and manufacturing allowances unless the producing artifact explicitly says otherwise.

## ZStateSearchContract

Required fields:

| Field | Meaning |
|---|---|
| `target_main_tip_z_m` | requested main spar loaded tip Z |
| `target_rear_tip_z_m` | requested rear spar loaded tip Z |
| `z_distribution_descriptor` | scale/exponent/spline/control points |
| `canonical_inverse_command` | exact command used |
| `tube_mass_kg` | selected tube mass |
| `jig_ground_clearance_min_m` | minimum jig clearance |
| `max_jig_vertical_prebend_m` | required jig prebend |
| `equivalent_tip_deflection_m` | structural recovery signal |
| `wire_tension_n` / `wire_margin_n` | wire loads |
| `moment_closure_status` | pass/fail/unsupported |
| `feasibility_status` | pass, diagnostic, fail |

The source of truth for target Z should be the selected summary JSON target shape, not legacy CSV exports if those lag the scaled target.

## Tier2ZoneEnvelopeContract

Required fields:

| Field | Meaning |
|---|---|
| `zone` | root, mid1, mid2, tip |
| `eta_min` / `eta_max` | zone span range |
| `Re_min` / `Re_p50` / `Re_max` | actual AVL Reynolds range |
| `Cl_min` / `Cl_p50` / `Cl_p90` / `Cl_max` | actual AVL Cl range |
| `Cm_work_point` | moment point for structure/trim coupling |
| `stall_margin_required_deg` | required margin |
| `query_quality_required` | archive and actual-query grade |

## CandidateVerdictContract

Required fields:

| Field | Meaning |
|---|---|
| `candidate_id` | unique id |
| `aero_rank` | rank by aerodynamic power |
| `production_rank` | rank among structure-feasible candidates |
| `P_crank_w` / `P_crank_conservative_w` | power estimates |
| `CDi` / `profile_cd` / `CD_total` | aero breakdown |
| `target_vs_avl_rms` / `outer_delta` | spanload realization |
| `spar_tube_mass_kg` | structure budget result |
| `jig_status` | jig feasibility |
| `airfoil_assignment` | root/mid1/mid2/tip |
| `promotion_status` | aero_best, production_best, research_only, rejected |

Promotion rule:

```text
production_best requires AVL sanity + Tier2 quality + structural budget pass
```
