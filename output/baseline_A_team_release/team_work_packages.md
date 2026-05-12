# Team Work Packages

Do not implement SU2/NSGA/propeller optimization in this release-builder task.

## Priority Queue

### WO-003: design-space freeze audit

- Objective: Confirm Baseline A external-shape and mission bounds are frozen enough for team work.
- Required output: verdict, changed files, verification, engineering caveats, and reviewer prompt.
- Decision gate: ask user only if large external shape, main/rear spar spec, weight/CG, procurement, or Baseline A reopen is affected.

### WO-004: manufacturable discretization/smoothness audit

- Objective: Check station spacing, rib bays, tube segmentation, and smoothness for shop handoff.
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
/goal
In /Volumes/Samsung SSD/hpa-mdo, execute WO-003: Design-Space Freeze Audit.
Read README.md, CURRENT_MAINLINE.md, output/baseline_A_team_release/, and docs/AI_WORK_ORDER_PROTOCOL.md first. Do not edit physics code unless the audit finds a release-blocking inconsistency. Verify whether Baseline A external shape, selected rib/torsion basis, managed CG, mass basis, and reopen triggers are internally consistent. Output pass/needs_fix/dangerous_assumption/reopen_risk, update docs only if needed, run relevant tests/ruff/git diff --check, and commit only this work order.
```

## Reviewer Prompt

Review the finished work order as代理總工程師. Check whether it preserves Baseline A as a team release, not final aircraft sign-off; whether it avoids mixing QPROP/XROTOR into structural blocker truth; and whether any finding requires user decision.
