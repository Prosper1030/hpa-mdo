# Baseline A team release

Verdict: `baseline_A_release_system_ready`

Baseline A is a team release package for current pathfinder execution. It is not final aircraft sign-off.

## Current Pathfinder

- Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
- P1 verdict: `p1_local_load_path_ready_for_coupon_fem`
- C04 original peel margin: `-0.893`
- Installed C04 fix: `saddle_ring_yoke_plus_secondary_clamp`
- Governing installed-fix margin: `0.8876`
- Updated screening mass: `106.828608 kg`
- Managed CG: `0.75 m`
- Required forward rebalance: `0.057304 m`
- Bounded physical twist: `1.906952370757391 deg`
- Ledger artifacts: `mass_budget.csv`, `cg_summary.json`, `margin_budget.md`, `mass_cg_margin_daily_review.md`

## frozen / do not casually change

- Phase J pathfinder narrative and candidate identity.
- Selected rib/torsion basis: 10 mm EPS-balsa hybrid, uniform 0.30 m, carbon face collar at y=2.328 m, rear75.
- Managed CG row at 0.75 m for screening closure.
- C04 baseline fail evidence remains part of the release record.

## controlled / can change with review

- C04 saddle-ring/yoke plus secondary clamp details.
- 3 m spar splice sizing and carbon tube RFQ tolerances.
- Mass/CG ledger and any rebalance action.
- Tail trim/stability assumptions and control authority margins.

## open validation / assigned to team

- Coupon tests for saddle/yoke/clamp and adhesive/lug-foot shear.
- C04 local FEM with shell/solid adhesive and clamp contact.
- 1 m wing-bay v2 build with skin sag and rib/collar load path evidence.
- Carbon tube RFQ and vendor tolerance check.
- Qualified aero-surface mapping for the direct spar-pair stress-test warning.

## reopen trigger / would force major redesign

- C04 saddle/yoke/clamp coupon or local FEM shows negative governing margin.
- Updated mass/CG cannot hold managed CG 0.75 m within rebalance limit.
- Tube RFQ cannot meet main/rear spar OD, wall, tolerance, or splice-fit assumptions.
- Qualified aero-surface mapping invalidates the current direct stress-test warning read.
- Tail trim/stability or control authority fails at managed CG.
- Main-wing SU2 baseline changes drag/power enough to invalidate mission margins.
- Manufacturing discretization forces large external-shape or spar-spec change.

## Team Start Authorization

Construction, structure, control, propulsion, and manufacturing teams may start assigned Baseline A work from this package. The allowed start is coupon/local FEM/RFQ/interface work, not unrestricted external-shape or aircraft sign-off work.
