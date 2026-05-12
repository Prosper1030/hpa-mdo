# Work Order Template

```text
/goal
In /Volumes/Samsung SSD/hpa-mdo, execute <WORK_ORDER_ID>: <TITLE>.

Role:
代理總工程師 / AI work-order executor. Keep Baseline A engineering-honest and
do not overclaim screening evidence.

Read first:
- README.md
- CURRENT_MAINLINE.md
- docs/AI_WORK_ORDER_PROTOCOL.md
- docs/work_orders/QUEUE.md
- output/baseline_A_team_release/
- <task-specific files>

Scope:
- Allowed writes: <files or directories>
- No-touch files: unrelated dirty output, especially output/phase12... and
  deleted output/phase14... unless explicitly requested
- Do not implement large SU2, NSGA, propeller optimization, random disturbance
  simulation, or full CAD automation unless this work order explicitly says so

Task:
<Concrete objective and expected artifact.>

Engineering boundary:
- Baseline A is a team release package, not final aircraft sign-off.
- P1 is ready for coupon/local FEM, not final build.
- C04 saddle/yoke/clamp is architecture-selected but still needs coupon/local FEM.
- QPROP/XROTOR is an independent propulsion lane unless the task is WO-005.
- Direct spar-pair stress-test remains a conservative mapping warning until
  qualified aero-surface mapping exists.

Required output:
- verdict: pass / needs_fix / dangerous_assumption / reopen_risk
- changed files
- verification
- engineering caveats
- reviewer prompt
- next recommended work order

Verification:
- run relevant tests
- run ruff on changed Python files
- run git diff --check
- stage only work-order files with git add -p
- commit one work order per commit

Reviewer prompt:
Review this work as代理總工程師. Check whether the evidence supports the verdict
inside the stated trust boundary, whether any claim was promoted beyond
screening/coupon/FEM evidence, and whether the task should reopen Baseline A or
only continue the queue.
```
