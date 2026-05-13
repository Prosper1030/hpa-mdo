# WO-006R2 CFD Recovery Campaign Report

Verdict: `wo006r2_bl_topology_blocker_isolated`

## Authority And Geometry

- Geometry: `current_avl_compromise_conservative_closed` from `/Volumes/Samsung SSD/hpa-mdo/output/go_mode_main_wing_candidate/final_candidate_package/geometry_exports/avl_parity/current_avl_compromise_conservative_closed/section_table.csv`.
- Mass authority: `98.5 kg`.
- Span authority: `34.332286 m` full / `17.166143 m` half.
- References: Sref `33.420059598 m^2`, Cref `1.003721543 m`, Bref `34.332286000 m`.
- External Baseline A shape changed: `false`.

## Old Evidence Reused

- Reused the old mesh-native route definition, not old Black Cat coefficients.
- Primary template: old `wing_h=0.20 m` HXT BL mesh with 1,125,409 cells.
- Failure boundary: old `wing_h=0.15 m` BL mesh with 1,515,251 cells and two non-positive BL quality items.
- Solver control: old 717,901-cell no-BL `INC_NAVIER_STOKES` 1000-iteration run, but only as non-drag-credible sign/reference evidence.

## Manual Research

See `manual_research_notes.md`. Key result: official SU2/Gmsh docs support the campaign policy that Euler/slip and no-BL tetra runs are not drag evidence; no-slip viscous/RANS cases need explicit wall markers and near-wall evidence.

## Attempts

### attempt_00_avl_parity_coarse_bridge_control

- route: `current_go_avl_parity_coarse_no_bl_bridge_control`
- mesh kind: `no_bl`
- volume elements: `3934`
- mesh gate: `pass`
- marker audit: `pass`
- solver status: `not_run`
- coefficient sanity: `None`

### attempt_01_replay_old_mesh_native_bl_template

- route: `current_go_faceted_hxt_bl_old_wing_h_0p20_template`
- mesh kind: `bl`
- volume elements: `None`
- mesh gate: `None`
- marker audit: `None`
- solver status: `None`
- coefficient sanity: `None`

### attempt_02_current_go_bl_coarser_quality_probe

- route: `current_go_faceted_hxt_bl_wing_h_0p25_quality_probe`
- mesh kind: `bl`
- volume elements: `None`
- mesh gate: `None`
- marker audit: `None`
- solver status: `None`
- coefficient sanity: `None`

### attempt_03_current_go_high_mesh_no_bl_solver_control

- route: `current_go_faceted_hxt_no_bl_high_mesh_solver_control`
- mesh kind: `no_bl`
- volume elements: `121694`
- mesh gate: `pass`
- marker audit: `pass`
- solver status: `not_run`
- coefficient sanity: `None`

## BL / y+ Status

`yplus_nearwall_summary.json` records the first-layer estimate. This is not a solver-derived surface y+ field unless a later SU2 postprocess provides it.

## Solver And Coefficients

Coefficients are accepted only if mesh quality, marker ownership, 1000+ iteration evidence, iterative gate, and non-negative coefficient sanity all pass. Otherwise Baseline A reopen remains `not_evaluated`.

## Blockers

- `attempt_01_replay_old_mesh_native_bl_template`: `Exception`; evidence `PLC point x=1.14443 y=-3.66499 z=0.0934631; section bracket 1-2 (dae31->dae31); crosses_airfoil_family=False`; next `localize_current_go_surface_panel_topology_near_plc_station_bracket_without_changing_external_shape`
- `attempt_02_current_go_bl_coarser_quality_probe`: `Exception`; evidence `PLC point x=0.897016 y=-10.6883 z=0.857425; section bracket 3-4 (dae31->dae31); crosses_airfoil_family=False`; next `localize_current_go_surface_panel_topology_near_plc_station_bracket_without_changing_external_shape`

## Engineering Caveats

- This is bounded CFD route recovery, not final aircraft sign-off.
- A passing SU2 run would still need mesh-pair/grid sensitivity before performance claims.
- Low-Re HPA drag remains transition-sensitive; SA/SST/LM assumptions need explicit turbulence/roughness evidence.

## Reviewer Prompt

```text
Review output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r2_cfd_recovery_campaign/. Check old_evidence_map.csv, route_decision_matrix.csv, yplus_nearwall_summary.json, mesh_attempts_summary.csv, solver_attempts_summary.csv, force_reference_audit.json, blocker_register.csv, and final_engineering_verdict.json. Judge whether the verdict is supported without promoting old Black Cat coefficients, blocked legacy mass/span values, no-BL drag, or negative CD into current Baseline A truth.
```

## Next Recommended Action

Use `next_goal.md` if the verdict is not `wo006r2_cfd_evidence_gate_ready`.
