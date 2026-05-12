# Baseline A Data-Authority Conflict Register

Verdict: `baseline_A_release_claims_unreliable` until all blocking rows are repaired.

This register is an adversarial sweep result. It classifies old outputs and generated reports as evidence, not authority, unless the authority table says otherwise.

## Blocking Conflicts

| ID | Category | Risk | Blocking status | Summary | Required repair |
|---|---|---|---|---|---|
| C-001 | mass / CG / rebalance | blocking | blocks_release_claims_and_downstream_power_cg | 98.5 kg is current design mass authority; 106.828608 kg is a suspect P1 screening aggregate and cannot drive current design mass, mission, CG, or RFQ truth. | Mass-basis reconciliation and measured/component ledger before any release, mission, CG, or procurement claim uses the aggregate. |
| C-002 | span / half-span / station / rib spacing | blocking | blocks_rfq_shop_and_station_control | Current pipeline evidence is 34.332286 m full span / 17.166143 m half-span; 16.5 m is local structural/splice screening only. | Reconcile pipeline geometry, station manifest, splice local basis, and vendor-screening convention before RFQ restoration. |
| C-003 | spar / splice / RFQ / procurement | blocking | wo005_draft_only | WO-005 RFQ artifacts were built from screening/local span and generated outputs. They are vendor-screening only, not purchase-ready. | Use authority table, conflict register, and station/span reconciliation before procurement use. |
| C-004 | drag / power / mission margin | high | blocks_full_pipeline_mission_verdict | WO-003 -9 W is only Stage-0 quick-screen warning, not latest full-pipeline mission truth. | Rebuild mission/power authority from the repaired mass/span basis before release claims. |
| C-005 | structure margin / C04 / coupon FEM | high | blocks_final_structure_signoff | P1/C04 evidence is coupon/local FEM readiness. It is not adhesive, laminate, buckling, hardware, or aircraft sign-off. | Coupon/local FEM, supplier allowables, tube-wall/collar/skin-sag evidence, and load-path review. |
| C-006 | tail / trim / stability / control | high | screening_only | Tail/CG/trim/stability claims remain screening assumptions, not measured CG, tail hardware, actuator, or flight-dynamics sign-off. | Measured mass/CG manifest, tailboom/pivot/actuator evidence, and control derivative validation. |
| C-007 | propulsion lane contamination | blocking | blocks_structural_verdict_language | QPROP/XROTOR must not pass or fail C04/rib/structural blockers. | Keep all structural verdicts free of propulsion pass/fail language. |
| C-008 | verdict / sign-off overclaim | blocking | blocks_baseline_A_release_claims | Release, ready, pass, RFQ, and FEM-readiness verdicts were too easy to read as current truth or final aircraft sign-off. | Use checker and authority table before adding release/work-order wording. |
| C-009 | tests that preserve stale constants | high | repair_needed | Some tests asserted stale constants as expected truth instead of checking authority classification. | Update tests to assert authority wording and safe classes. |
| C-010 | scripts that read old generated outputs as truth | high | repair_needed | Release/RFQ scripts read generated P1/splice/manufacturing outputs as if they were release authority. | Scripts must emit authority metadata and avoid promotion wording. |

## Current-Channel Violations
- None after current wording repair.
