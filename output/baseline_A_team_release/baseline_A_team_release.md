# Baseline A team release

Verdict: `baseline_A_data_authority_repair_in_progress`

Baseline A is under data-authority repair. This package is retained as screening evidence and task coordination material; it is not current release authority and not final aircraft sign-off.

## Data Authority Repair Gate

- Current design gross mass authority: `98.5 kg`.
- Suspect P1 screening aggregate: `106.828608 kg` (not current design mass truth).
- Current pipeline span evidence: `34.332286 m` full span / `17.166143 m` half-span.
- Local/splice screening half-span: `16.5 m`, not procurement truth.
- WO-005 RFQ pack remains draft/vendor-screening only.
- WO-006 SU2 is paused until data authority is restored.

## Current Pathfinder

- Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
- P1 verdict: `p1_local_load_path_ready_for_coupon_fem`
- C04 original peel margin: `-0.893`
- Installed C04 fix: `saddle_ring_yoke_plus_secondary_clamp`
- Governing installed-fix margin: `0.8876`
- Suspect P1 screening aggregate: `106.828608 kg`
- Managed CG: `0.75 m`
- Required forward rebalance: `0.057304 m`
- Bounded physical twist: `1.906952370757391 deg`
- Ledger artifacts: `mass_budget.csv`, `cg_summary.json`, `margin_budget.md`, `mass_cg_margin_daily_review.md`

## authority-controlled / do not casually change

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
- Tube vendor-screening evidence cannot meet main/rear spar OD, wall, tolerance, or splice-fit assumptions after authority repair.
- Qualified aero-surface mapping invalidates the current direct stress-test warning read after authority repair.
- Tail trim/stability or control authority fails at managed CG.
- Main-wing SU2 remains paused until data authority is restored; later SU2 baseline changes drag/power enough to invalidate mission margins.
- Manufacturing discretization forces large external-shape or spar-spec change.

## Team Start Authorization

Teams may use this package only for bounded screening, coupon/local FEM planning, interface review, and draft vendor questions. It does not authorize RFQ purchase action, shop drawing release, SU2 release claims, or aircraft sign-off work.
