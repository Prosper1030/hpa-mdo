# Codex Go Execution Prompt

```text
Read the master plan in:
output/goals/hpa_wing_go_mode_master_plan/

Goal:
Find a structure-feasible, aerodynamically efficient, production-facing HPA main
wing candidate for the Birdman-style mission, or prove the physical/modeling
blocker that prevents it.

Follow GOAL.md, AUTONOMOUS_EXECUTION_POLICY.md, PIPELINE_TARGETS_AND_THRESHOLDS.md,
WORKSTREAMS.md, and DECISION_TREE.md.

Do not work as a small MVP checklist agent. Work as a goal-oriented engineering
agent. Keep iterating through Fourier-AVL control, smooth geometry,
structure-budgeted loaded shape, Tier2 airfoil selection, aero-structure
closure, and structural trust until either:
A. a production-facing candidate satisfies the success criteria, or
B. the blocker is proven with evidence.

Do not change production ranking, add hard gates, run broad CST/NSGA, or use FEM
as broad search without explicit justification. Use reports as evidence, not as
the endpoint. Commit independent completed work in separate task-scoped commits.
```
