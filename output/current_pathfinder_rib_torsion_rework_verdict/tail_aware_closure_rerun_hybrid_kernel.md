# Tail-Aware Aeroelastic Closure

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `ready_for_fem_apdl_loadcase_package`
Twist-source verdict: `ready_for_aeroelastic_mapping_fix`
Blockers: `[]`
Warnings: `['negative_diagnostic_stall_margin_not_gate', 'direct_spar_pair_stress_test_above_bound_conservative_mapping']`

## Closure Read

- Fixed-point converged: `True` after `3` iteration(s).
- Final CG: `0.750000` m using `0.079276` m forward rebalance on `56.0` kg; uncompensated `0.793296` m is rejected.
- Trim alpha / delta_H: `-1.606662` deg / `10.207015` deg.
- H-tail reserve / static margin: `4.792985` deg / `0.094301` MAC.
- C_n_beta / V-tail reserve: `0.014030` / `16.716831` deg.
- Elastic twist max / tip: `3.449253` deg / `0.388721` deg.
- Twist projection: `direct_spar_pair_rotation_to_avl_ainc_stress_test`.
- Stall margin min: `-0.135300` Cl using `diagnostic_constant_section_cl_limit_not_gate`.
- Root bending ratio vs baseline AVL load: `0.900942`.

## Twist Source Audit

- Direct spar-pair rotation max: `3.449294` deg at y=`1.164` m.
- Elastic-axis / quarter-chord projection max: `3.449294` deg.
- Conservative bounded physical projection max: `2.070316` deg at y=`1.164` m.
- Dominant component at direct max station: `lift_only` with component twists `{'lift_only': -5.0912863493849105, 'aerodynamic_torque_only': 1.7242515669387546, 'self_weight_only': 1.1640605836952198}` deg.
- Audit CSV: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/tail_aware_closure_rerun_hybrid_kernel/final/twist_source_audit.csv`; component CSV: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/tail_aware_closure_rerun_hybrid_kernel/final/twist_source_components.csv`.
- Engineering read: The direct spar-pair stress-test exceeds the bound but the bounded physical projection clears it. Prioritize qualified aero-surface / elastic-axis mapping before adding stiffness mass.

## Selected Basis Audit For FEM/APDL Package

- Rib: `eps_balsa_cap_hybrid_10mm` at `0.300` m target spacing; materialized max subbay `0.297063` m; full-wing stations/ribs `121`.
- Rear spar participation: `bounded_65pct_screening`; warping knockdown `0.819399`.
- Effective EI/GJ ratios vs finite-rib rear=1.0 upper bound: `n/a` / `2.033`.
- Closure aero load owner for rework: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/tail_aware_closure_rerun_hybrid_kernel/runs/iteration_03/tail_trim_avl/trimmed/concept_spanwise.fs` with redistribution CSV `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/tail_aware_closure_rerun_hybrid_kernel/final/wing_spanload_redistribution.csv`.
- Elastic twist / alpha_eff CSV: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/tail_aware_closure_rerun_hybrid_kernel/final/elastic_twist_alpha_eff.csv`.

## Mass / Drag / Power

- Rib mass delta: `5.365042` kg; tail mass delta `1.172727` kg.
- Tail CD0 increment: `0.002352`; tail profile power increment `13.332` W.

## Engineering Boundary

- Current verdict is not package-ready; use this closure as the rework basis until the twist/stiffness blocker is closed.
- This is a FEM/APDL loadcase-package basis only, not final composite, shell, root fitting, wire termination, tail pivot, rib attach, or flight hardware sign-off.
- Direct spar-pair rotation projected into AVL incidence is a conservative stress-test proxy, not a qualified aero-surface twist measurement.
- The selected stiffness is still a bounded screening surrogate; FEM/APDL must carry the listed load owner and CG/rebalance assumption explicitly.
