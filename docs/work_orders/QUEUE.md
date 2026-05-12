# Baseline A Work Order Queue

Queue owner:代理總工程師 / AI 工作總控.

Current release package:

- `output/baseline_A_team_release/`
- verdict: `baseline_A_release_system_ready`
- current structural blocker verdict: `p1_local_load_path_ready_for_coupon_fem`

## Queue Rules

- Pick the first unblocked work order unless a newer user instruction overrides it.
- Do not bundle independent work orders into one commit.
- Keep SU2, NSGA, propeller optimization, random disturbance simulation, and full
  CAD automation as queued work unless the selected work order explicitly starts
  that lane.
- Do not promote screening evidence into final aircraft sign-off.
- Do not stage unrelated dirty `output/phase12...` or deleted `output/phase14...`
  files.

## Priority Queue

| ID | Status | Work order | Owner lane | Decision risk |
|---|---|---|---|---|
| WO-001 | ready | design-space freeze audit | chief engineering | reopen risk if external shape/source trace is inconsistent |
| WO-002 | ready after WO-001 | manufacturable discretization/smoothness audit | manufacturing + geometry | may affect external shape or rib station details |
| WO-003 | ready after WO-001 | mass/CG/margin ledger | chief engineering | may affect CG/rebalance |
| WO-004 | queued | main-wing SU2 baseline validation | aero validation | may affect drag/power claim, not structural blocker truth |
| WO-005 | queued | QPROP/XROTOR propulsion interface | propulsion | independent lane, feed only reviewed interfaces back |
| WO-006 | queued | turn/stall competition gate | aero + competition | may affect mission gate |
| WO-007 | queued | control derivative matrix and tail motor authority | controls | may affect tail/control authority |
| WO-008 | queued | tailboom/vertical strut first-order model | structures + controls | may affect tail hardware load path |
| WO-009 | background | airfoil database CST/NSGA background lane | airfoil research | background only until explicitly promoted |
| WO-010 | background | report/CAD/export automation | release tooling | after release semantics settle |

## Next Recommended Work Order

```text
/goal
In /Volumes/Samsung SSD/hpa-mdo, execute WO-001 design-space freeze audit.

Role:代理總工程師 / AI reviewer. Keep Baseline A engineering-honest.

Read first:
- README.md
- CURRENT_MAINLINE.md
- docs/AI_WORK_ORDER_PROTOCOL.md
- docs/work_orders/QUEUE.md
- output/baseline_A_team_release/

Task:
Verify whether Baseline A external shape, current pathfinder source trace,
selected rib/torsion basis, managed CG, updated screening mass basis, C04 fix
state, and reopen triggers are internally consistent. Do not implement new
physics. Do not run large SU2/NSGA/propeller/CAD work. Patch only docs or small
release metadata if an inconsistency would mislead future agents.

Required output:
- verdict: pass / needs_fix / dangerous_assumption / reopen_risk
- changed files
- verification
- engineering caveats
- reviewer prompt
- next recommended work order

Verification:
- run relevant tests if any file changed
- run ruff on changed Python files if any
- run git diff --check
- git add -p only this work-order scope and commit
```

## Reviewer Prompt Template

```text
Review the completed work order as代理總工程師.

Check:
1. Does it preserve Baseline A as a team release, not final aircraft sign-off?
2. Did it keep C04 original peel fail evidence visible?
3. Did it keep P1 at coupon/local FEM readiness, not final build?
4. Did it keep QPROP/XROTOR independent from the structural blocker verdict?
5. Did it avoid accepting uncompensated CG?
6. Did it identify any user decision only when the issue affects external
   shape, spar spec, weight/CG, procurement, or Baseline A reopen?

Return pass / needs_fix / dangerous_assumption / reopen_risk with line-level
evidence.
```
