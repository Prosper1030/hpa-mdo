# Tail-Aware Aeroelastic Closure

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `needs_aeroelastic_geometry_or_stiffness_rework`
Blockers: `['elastic_twist_exceeds_screening_bound']`
Warnings: `['negative_diagnostic_stall_margin_not_gate']`

## Closure Read

- Fixed-point converged: `True` after `3` iteration(s).
- Final CG: `0.750000` m using `0.091302` m forward rebalance on `56.0` kg; uncompensated `0.801026` m is rejected.
- Trim alpha / delta_H: `-2.605118` deg / `11.241154` deg.
- H-tail reserve / static margin: `3.758846` deg / `0.098824` MAC.
- C_n_beta / V-tail reserve: `0.012409` / `17.096162` deg.
- Elastic twist max / tip: `5.413617` deg / `0.573576` deg.
- Twist projection: `direct_spar_pair_rotation_to_avl_ainc_stress_test`.
- Stall margin min: `-0.223400` Cl using `diagnostic_constant_section_cl_limit_not_gate`.
- Root bending ratio vs baseline AVL load: `0.863504`.

## Selected Basis Audit For FEM/APDL Package

- Rib: `balsa_sheet_3mm` at `0.300` m target spacing; materialized max subbay `0.297063` m; full-wing stations/ribs `121`.
- Rear spar participation: `bounded_50pct_screening`; warping knockdown `0.502460`.
- Effective EI/GJ ratios vs finite-rib rear=1.0 upper bound: `0.599` / `0.568`.
- Closure aero load owner for rework: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_tail_aware_aeroelastic_closure/runs/iteration_03/tail_trim_avl/trimmed/concept_spanwise.fs` with redistribution CSV `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_tail_aware_aeroelastic_closure/final/wing_spanload_redistribution.csv`.
- Elastic twist / alpha_eff CSV: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_tail_aware_aeroelastic_closure/final/elastic_twist_alpha_eff.csv`.

## Mass / Drag / Power

- Rib mass delta: `3.029671` kg; tail mass delta `1.172727` kg.
- Tail CD0 increment: `0.002352`; tail profile power increment `13.332` W.

## Engineering Boundary

- Current verdict is not package-ready; use this closure as the rework basis until the twist/stiffness blocker is closed.
- This is a FEM/APDL loadcase-package basis only, not final composite, shell, root fitting, wire termination, tail pivot, rib attach, or flight hardware sign-off.
- Direct spar-pair rotation projected into AVL incidence is a conservative stress-test proxy, not a qualified aero-surface twist measurement.
- The selected stiffness is still a bounded screening surrogate; FEM/APDL must carry the listed load owner and CG/rebalance assumption explicitly.
