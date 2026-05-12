# Team Work Packages

Do not implement SU2/NSGA/propeller optimization in this release-builder task.

## Completed Work Orders

### WO-003: design-space freeze audit

- Completion read: Completed as Stage-0 screening; authority repair now supersedes freeze/release claims.

### WO-004: manufacturable discretization/smoothness audit

- Completion read: Completed with verdict `geometry_freeze_needs_fix`; no large external-shape reopen, but station/span/splice authority must be reconciled before RFQ/shop use.

### WO-005: carbon tube RFQ + procurement pack

- Completion read: Downgraded to draft/vendor-screening only; mass/span authority repair is required before procurement or drawing-control use.

## Priority Queue

### WO-006: main-wing SU2 baseline validation

- Objective: WO-006 remains paused until data authority is restored; do not run SU2 for release claims yet.
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
/goal In /Volumes/Samsung SSD/hpa-mdo, keep WO-006 paused and execute the next data-authority repair item.
Read README.md, CURRENT_MAINLINE.md, docs/reports/baseline_A_data_authority_audit.md, docs/reports/baseline_A_data_authority_conflict_register.md, and output/baseline_A_team_release/data_authority_table.csv first. Do not run SU2, QPROP, XROTOR, prop optimization, or procurement actions. Repair the next blocking mass/span/station authority issue, update tests and generated wording, run the data-authority checker, and commit only that work order.
```

## Reviewer Prompt

Review the finished work order as代理總工程師. Check whether it preserves Baseline A as a team release, not final aircraft sign-off; whether it avoids mixing QPROP/XROTOR into structural blocker truth; and whether any finding requires user decision.
