# Baseline A Design-Space Freeze Audit

Work order: `WO-003 Design-Space Freeze Audit`
Verdict: `baseline_A_freeze_reasonable`

Baseline A remains reasonable to freeze for team work. I did not find explicit reopen-trigger evidence that a nearby manufacturable candidate clearly dominates the released pathfinder. The strongest nearby fast-model row is `seed_best_power_6p6_span35_AR40_CD0p016`, which reduces quick-screen required crank power by `4.63%` versus the release-mass/tail-charge Baseline A screen. That is below the 5-8% power reopen trigger, is outside the current released geometry chain, and has `cl_band=high_but_possible` / `stall_band=caution`.

## Scope And Boundary

This is a fast audit, not a redesign campaign. I used existing release artifacts, Stage-0 mission design-space outputs, and the existing `hpa_mdo.mission.quick_screen` model. I did not run heavy FEM, SU2, NSGA, propeller optimization, random disturbance simulation, or CAD/STEP automation.

Baseline A is still a team-release package, not final aircraft sign-off. P1 means coupon/local FEM readiness. The C04 original peel fail evidence remains part of the release record.

## Sources Read

- `README.md`
- `CURRENT_MAINLINE.md`
- `docs/AI_WORK_ORDER_PROTOCOL.md`
- `docs/work_orders/QUEUE.md`
- `output/baseline_A_team_release/`
- `output/mission_design_space/`
- `output/go_mode_main_wing_candidate/final_candidate_package/candidate_summary.csv`
- `output/current_pathfinder_spar_splice_design/splice_design_report.md`
- `output/current_pathfinder_materialized_rib_contract_audit/`
- `output/current_pathfinder_rib_torsion_design_search/`

## Baseline A Reference

| Item | Value | Read |
|---|---:|---|
| Candidate | `current_avl_compromise_conservative_closed` / `eps_balsa_cap_hybrid_10mm...rear75` | release basis |
| Span | `34.332286 m` | exact geometry manifest |
| Area | `33.420060 m^2` | exact geometry manifest |
| Computed AR | `35.269` | below Stage-0 AR grid 37-40 |
| Release mass | `106.828608 kg` | screening estimate ledger |
| Managed CG | `0.75 m` | accepted screening row |
| Uncompensated CG | `0.780039 m` | explicitly rejected |
| Pre-tail main-wing P_crank | `174.600 W` (`178.882 W` conservative) | final candidate package |
| Tail CD0 / power charge | `0.002352` / `13.332 W` | release ledger placeholder |
| Quick-screen total with release mass + tail CD0 | `203.319 W`, margin `-9.140 W` | audit warning, not final mission sign-off |
| Bounded physical twist | `1.906952 deg` | below 3 deg screening bound |
| Direct spar-pair stress-test | `3.177742 deg` | conservative mapping warning |
| Rib basis | `0.30 m` physical stations/bays | materialized enough for freeze audit; details still WO-004/local FEM |
| 3 m panel assumption | structural half-span `16.5 m`, 5 splices per half, `3.847 kg` full-wing | plausible enough to freeze for team work |

## Candidate Comparison Read

See `candidate_compare_table.csv` for the numeric table. The important engineering read is:

- Directly using `output/mission_design_space/candidate_seed_pool.csv` would be misleading because that seed pool uses `96-101 kg` and AR `37-40`, while Baseline A release is `106.828608 kg` and AR `35.269`.
- I therefore re-evaluated the most relevant rows at release mass using the same quick-screen model, then treated rows without geometry/torsion/CG/release evidence as pre-gate candidates only.
- The best nearby row by fast power is span `35 m`, AR `40`, CD0 `0.016`, e `0.95`, speed `6.6 m/s`. It is about `4.63%` better than the release-total quick-screen baseline, but it is not a clear dominance case because it requires a different upstream planform/AR and has no downstream loaded-Z, tail, CG, torsion, splice, or P1 load-path chain.
- Rounding Baseline A span to the nearest `0.1 m` changes quick-screen power by only `-0.0026%`; span-grid discretization alone does not force reopen.

## Reopen Trigger Check

| Trigger | Status | Engineering read |
|---|---|---|
| Power improvement > roughly 5-8% | `not_triggered` | best nearby fast row is `4.63%`; below trigger and not chain-complete |
| Weight improvement > 2-3 kg | `not_evaluable_not_triggered` | no alternate candidate has comparable structural/tail/splice/rib mass ledger |
| Unrecoverable trim / CG / torsion / structural fail | `not_triggered` | managed CG, tail status, bounded twist, and P1 readiness remain screening-pass; uncompensated CG stays rejected |
| Mission fail | `watch_not_reopen` | release-mass + tail-CD0 quick-screen margin is about `-9 W`; this is a power-budget warning for validation, not explicit reopen evidence |
| Manufacturable discretization forces major shape or spar change | `not_triggered` | span rounding is benign; rib/splice assumptions are plausible enough for freeze, while WO-004 must audit details |

## Engineering Caveats

- The quick-screen total-power warning matters. If later SU2, QPROP/XROTOR, turn/stall, or measured tail/drag data confirm a persistent power deficit, Baseline A may move from freeze-reasonable to reopen-risk.
- The Stage-0 seed pool is not a replacement for promoted trace. Baseline A still needs a cleaner current mission -> Fourier/spanload -> realized geometry manifest.
- AR 40 looks attractive in a fast model, but it also means smaller area/mean chord and a higher CL burden. It is not an obvious manufacturing or structural free lunch.
- The 3 m splice path is plausible, but the inboard y=3 m joint has essentially zero bending margin in the current screening report. That is acceptable for freeze audit only because procurement/detail validation is still queued.
- C04/P1 remains coupon/local FEM readiness, not build sign-off.

## Repeatability

Helper artifacts in this directory:

- `candidate_compare_table.csv`
- `baseline_A_reopen_risk.json`
- `audit_method_inputs.json`

Relevant regeneration commands:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/mission_design_space_explorer.py --config configs/mission_design_space_example.yaml
PYTHONPATH=src ./.venv/bin/python scripts/build_baseline_a_release.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_p1_load_path_mass_closure.py
```

The exact z-state structure replay command is preserved in `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary/runs/target_main_tip_z_2p700m/command.txt`.

## Next Work Order

Proceed to `WO-004 Manufacturable Smoothness / Discretization Audit`. It should inspect section transitions, chord/twist/dihedral smoothness, 0.30 m rib materialization, 3 m segment boundaries, splice placement, and whether the structural `16.5 m` half-span and aerodynamic `17.3 m` station extent are being mixed in any team-facing assumptions.
