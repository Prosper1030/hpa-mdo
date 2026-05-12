# Team Work Packages

Do not implement SU2/NSGA/propeller optimization in this release-builder task.

## Completed Work Orders

### WO-003: design-space freeze audit

- Completion read: Completed with verdict `baseline_A_freeze_reasonable`; power-budget watch item remains.

### WO-004: manufacturable discretization/smoothness audit

- Completion read: Completed with verdict `geometry_freeze_needs_fix`; no large external-shape reopen, but station/span/splice manifest must be controlled before RFQ/shop use.

## Priority Queue

### WO-005: carbon tube RFQ + procurement pack

- Objective: Turn screening tube, splice, tolerance, and station assumptions into a vendor-facing question pack without committing procurement.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-006: main-wing SU2 baseline validation

- Objective: Queue a bounded CFD baseline; do not use it as current structural-blocker truth.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-007: QPROP/XROTOR propulsion interface

- Objective: Translate independent propulsion results into reviewed thrust/torque/mass interfaces.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-008: turn/stall competition gate

- Objective: Define competition maneuver and stall evidence gates before expanding search.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-009: control derivative matrix and tail motor authority

- Objective: Build controls-facing derivative and actuator authority matrix.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-011: tailboom/vertical strut first-order model

- Objective: Add first-order structural load path model for tailboom and vertical strut.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-012: airfoil database CST/NSGA background lane

- Objective: Run as background database improvement, not as Baseline A blocker.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-013: report/CAD/export automation

- Objective: Automate reports and export bundles after release package semantics are stable.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

## Next Recommended Codex Goal

```text
/goal In /Volumes/Samsung SSD/hpa-mdo, execute WO-005: Carbon Tube RFQ + Procurement Pack.
Read README.md, CURRENT_MAINLINE.md, output/baseline_A_team_release/, output/baseline_A_team_release/manufacturable_geometry_audit/, and docs/AI_WORK_ORDER_PROTOCOL.md first. Build a vendor-facing screening RFQ pack for carbon tubes, splice fit, tolerances, QA coupons, 3 m shipping segments, station/span/splice manifest, and supplier questions. Do not place orders, choose a supplier, or change spar specs without user decision. Carry WO-004 warnings explicitly, output verdict, changed files, verification, engineering caveats, reviewer prompt, and next work order; run relevant tests/ruff/build release/git diff checks, then commit only WO-005.
```

## Reviewer Prompt

Review the finished work order as代理總工程師. Check whether it preserves Baseline A as a team release, not final aircraft sign-off; whether it avoids mixing QPROP/XROTOR into structural blocker truth; and whether any finding requires user decision.
