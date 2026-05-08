# Pipeline v2 Stage Data Contracts

## Contract Rule

Each stage must write explicit inputs, outputs, units, and trust labels. The
pipeline should never silently compare quantities that use different span,
mass, Z, or half-span conventions.

## Stage 0: Mission Contract

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `target_range_km` | km | Mission distance, currently `42.195`. |
| `V_mps` | m/s | Cruise speed, approximately `6.5-6.7`. |
| `rho_kg_m3` | kg/m3 | Air density. |
| `m_total_kg` | kg | Total design mass or mass range. |
| `span_m` | m | Wing span. |
| `aspect_ratio` | - | Aspect ratio. |
| `eta_prop` | - | Propeller efficiency. |
| `eta_drive` | - | Drivetrain efficiency. |
| `CDA_nonwing_m2` | m2 | Nonwing drag reserve. |
| `tube_spar_mass_budget_kg` | kg | Structural tube/spar budget. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `S_m2` | m2 | Wing area, `span^2 / AR`. |
| `q_pa` | Pa | Dynamic pressure. |
| `CL_req` | - | Required lift coefficient. |
| `CD0_total_budget` | - | Profile plus nonwing reserve. |
| `P_crank_budget_w` | W | Crank power estimate. |
| `mass_basis` | text | Defines whether mass is tube-only, tube+wire, or total structure. |

## Stage 1: Fourier-AVL Calibration

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `case_id` | text | Candidate or calibration case. |
| `eta` | - | Half-span coordinate, root `0`, tip `1`. |
| `theta` | rad | Lifting-line coordinate with documented convention. |
| `Lprime_Npm` | N/m | AVL lift per unit span. |
| `chord_m` | m | Local chord. |
| `cl_local` | - | AVL local section lift coefficient. |
| `V_mps` | m/s | Cruise speed. |
| `rho_kg_m3` | kg/m3 | Air density. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `A1,A3,A5,A7` | - | Fitted Fourier coefficients. |
| `r3,r5,r7` | - | `A_n / A1` ratios. |
| `e_fourier_fit` | - | Efficiency implied by fitted coefficients. |
| `e_avl_cdi` | - | AVL induced-drag efficiency. |
| `spanload_rms_delta` | - | Normalized target-vs-AVL mismatch. |
| `bending_proxy_delta` | - | Difference in bending proxy. |
| `bridge_status` | text | `calibrated`, `definition_mismatch`, `geometry_authority_limited`, etc. |

### Required Artifacts

- `spanload_definition.md`
- `avl_to_fourier_fit.csv`
- `fourier_command_to_avl_realized.csv`
- `fourier_avl_calibration_report.md`
- `recommended_fourier_bridge.md`

## Stage 2: Fourier Spanload Candidate Generator

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `bridge_version` | text | Fourier-AVL bridge used. |
| `commanded_r3,r5,r7` | - | Requested low-order spanload shape. |
| `CL_req` | - | Mission required CL. |
| `AR` | - | Aspect ratio. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `e_theory` | - | Fourier theoretical efficiency. |
| `e_expected_avl` | - | Bridge-corrected expected AVL efficiency. |
| `root_bending_proxy` | normalized | Structural burden estimate. |
| `outer_lift_fraction` | - | Outer loading indicator. |
| `local_cl_risk` | text/value | Risk of exceeding airfoil capability. |
| `structural_burden_proxy` | text/value | Relative structural difficulty. |

## Stage 3: Smooth Geometry Realization

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `span_m` | m | Span. |
| `S_m2` | m2 | Area. |
| `AR` | - | Aspect ratio. |
| `commanded_spanload_id` | text | Stage 2 spanload target. |
| `loaded_z_seed` | m | Provisional loaded-shape seed. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `station_y_m` | m | Geometry station. |
| `chord_m` | m | Smooth chord. |
| `twist_deg` | deg | Incidence / twist. |
| `z_m` | m | Provisional aerodynamic surface z. |
| `chord_slope` | - | Smoothness diagnostic. |
| `chord_curvature` | - | Smoothness diagnostic. |
| `geometry_validity_status` | text | Production-like geometry status. |

## Stage 4: AVL Realization Check

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `geometry_file` | path | AVL geometry. |
| `CL_req` | - | Target CL. |
| `airfoil_placeholder_mode` | text | No-airfoil, seed, or provisional. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `alpha_at_CL_req_deg` | deg | AVL trim angle. |
| `CDi` | - | Induced drag coefficient. |
| `e_CDi` | - | AVL induced efficiency. |
| `avl_spanload_csv` | path | Actual spanload. |
| `local_cl_max` | - | Max local Cl. |
| `Re_min, Re_max` | - | Local Reynolds range. |
| `fourier_mismatch_status` | text | Whether target was realized. |
| `root_bending_proxy_avl` | normalized | Bending burden from AVL actual loading. |

## Stage 5: Structure-Budgeted Loaded-Z Search

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `avl_spanload_csv` | path | Stage 4 actual loading. |
| `tube_spar_mass_budget_kg` | kg | Budget, around `10.5-11.5 kg` class. |
| `loaded_z_family_id` | text | Candidate loaded-shape family. |
| `wire_contract` | text/path | Wire attach / pretension assumptions. |
| `material_recipe_id` | text | CFRP tube recipe. |

### Required Z Fields

| Field | Unit | Meaning |
| --- | ---: | --- |
| `aero_surface_z_m` | m | Aerodynamic surface z. |
| `main_beam_z_m` | m | Main spar beam-line z. |
| `rear_beam_z_m` | m | Rear spar beam-line z. |
| `built_in_geometric_z_m` | m | Built-in geometric z. |
| `elastic_deflection_z_m` | m | Structural deflection under load. |
| `total_loaded_z_m` | m | Built-in plus elastic loaded state. |
| `total_cruise_effective_dihedral_deg` | deg | Target around `6-7 deg` if possible. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `tube_mass_full_span_kg` | kg | Mass basis must be explicit. |
| `total_structural_mass_kg` | kg | If available, include components. |
| `main_tip_deflection_m` | m | Main spar tip deflection. |
| `rear_tip_deflection_m` | m | Rear spar tip deflection. |
| `wire_tension_n` | N | Wire reaction/tension. |
| `jig_ground_clearance_margin_m` | m | Jig clearance. |
| `jig_feasibility_status` | text | Inverse-design feasibility. |
| `moment_closure_status` | text | Diagnostic, not final truth. |
| `structure_trust_label` | text | Screening, FEM-needed, or final-grade. |

### Required Artifacts

- `z_state_structure_budget_sweep.csv`
- `feasible_loaded_shape_shortlist.csv`
- `z_definition_audit.md`
- `recommended_loaded_z_states.md`

## Stage 6: AVL Recheck On Realizable Loaded Shape

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `realizable_loaded_shape_file` | path | Loaded geometry from Stage 5. |
| `CL_req` | - | Mission CL. |
| `candidate_id` | text | Candidate trace ID. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `loaded_shape_e_CDi` | - | AVL efficiency on realizable shape. |
| `loaded_shape_CDi` | - | Induced drag on realizable shape. |
| `loaded_shape_spanload_csv` | path | Actual spanload. |
| `loaded_shape_local_cl_re_csv` | path | Local Cl/Re envelope. |
| `stall_margin_min` | - | Worst margin. |
| `bending_proxy_loaded_shape` | normalized | Updated structural loading burden. |

## Stage 7: Tier2 Full-Alpha Airfoil Selection

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `loaded_shape_local_cl_re_csv` | path | Stage 6 actual query envelope. |
| `tier2_airfoil_db` | path | Full-alpha polar database. |
| `zone_definition` | path/text | root/mid1/mid2/tip. |
| `combo_cap` | count | Maximum rerun combinations. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `best_aero_assignment` | text/json | Lowest drag feasible assignment. |
| `best_production_assignment` | text/json | Conservative production-quality assignment. |
| `profile_cd` | - | Integrated profile drag. |
| `CD0_total` | - | Profile plus nonwing reserve. |
| `P_crank` | W | Crank power estimate. |
| `P_crank_conservative` | W | Conservative estimate. |
| `stall_margin_min` | - | Worst margin. |
| `actual_query_quality` | text | Quality of local Cl/Re lookup. |
| `archive_quality` | text | Airfoil database quality status. |

## Stage 8: Aero-Structure Closure

### Inputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `selected_airfoils` | text/json | Stage 7 assignment. |
| `loaded_shape_geometry` | path | Stage 5/6 geometry. |
| `structure_recipe` | text/json | Tube/wire/material recipe. |

### Outputs

| Field | Unit | Meaning |
| --- | ---: | --- |
| `closure_e_CDi_delta_pct` | % | Induced efficiency change. |
| `closure_spanload_delta_pct` | % | Loading change. |
| `closure_deflection_delta_pct` | % | Structural response change. |
| `closure_mass_delta_pct` | % | Mass change if recipe updated. |
| `closure_status` | text | `closed`, `minor_mismatch`, `loop_back_required`. |

## Stage 9: Structural Trust Layer

### Trust Labels

| Label | Meaning |
| --- | --- |
| `daily_screening` | Good enough for fast candidate comparison. |
| `diagnostic_fem_supported` | Supported by shell/APDL/CalculiX spot evidence, but not final signoff. |
| `fem_spot_check_required` | Needs external or shell FEM before design decision. |
| `not_final_truth` | Do not use for final design. |
| `final_structure_grade` | Reserved for finalist verification after composite/stress/buckling/joint checks. |

## Stage 10: Final Verification

Finalists only. Required outputs are not part of MVP:

- 2D SU2 airfoil verification,
- 3D SU2 / VSPAERO / CFD if needed,
- CalculiX / ANSYS structural spot checks,
- discrete CFRP layup,
- Tsai-Wu,
- buckling,
- joints,
- manufacturing package,
- drawing-ready package.
