# Canonical Hybrid CFD Release v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the WO-006 R-series mixed handoff from active CFD delivery and force all future CFD work through `canonical_hybrid_halfwing_v0`.

**Architecture:** Treat R27/R28/R29/R30 as forensic evidence, then use one release manifest as the only active route state. A small validator blocks all-tet BL handoff, closure-force mixing, non-release statuses, conservative-numerics success claims, and double-counted AOA before any new mesh or solver work can be promoted.

**Tech Stack:** Python 3.10, PyYAML, pytest, existing `output/baseline_A_team_release/wo006_su2_baseline_validation/` artifact tree.

---

### Task 1: Phase 0 Route Retirement Gate

**Files:**
- Create: `tests/test_canonical_hybrid_cfd_release_policy.py`
- Create: `scripts/check_canonical_hybrid_cfd_release.py`
- Create: `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/manifest.yaml`
- Modify: `README.md`
- Modify: `CURRENT_MAINLINE.md`
- Modify: `docs/reports/wo006_cfd_problem_solution_register.md`

- [x] **Step 1: Write the failing policy test**

Run: `./.venv/bin/pytest tests/test_canonical_hybrid_cfd_release_policy.py -q`

Expected before implementation: FAIL because `scripts/check_canonical_hybrid_cfd_release.py` is missing.

- [x] **Step 2: Add the validator and manifest**

Implement `validate_manifest()` so it rejects retired R-routes, non-release statuses, all-tet BL handoff, closure markers inside primary force monitoring, nonzero baseline AOA, and conservative numerics as success.

- [x] **Step 3: Run targeted tests**

Run: `./.venv/bin/pytest tests/test_canonical_hybrid_cfd_release_policy.py -q`

Expected: PASS.

- [x] **Step 4: Sync the current-channel docs**

Add a short front-door note that `canonical_hybrid_halfwing_v0` is active and WO-006R25 through WO-006R30 are forensic-only.

- [ ] **Step 5: Run guardrails**

Run:

```bash
./.venv/bin/pytest tests/test_canonical_hybrid_cfd_release_policy.py tests/test_baseline_a_data_authority.py -q
python3 scripts/check_canonical_hybrid_cfd_release.py
python3 scripts/check_baseline_a_data_authority.py --check-only
git diff --check
```

Expected: all commands pass.

- [ ] **Step 6: Commit**

Stage only this task's files, force-adding the ignored `output/.../cfd_release_v0/manifest.yaml`, then commit:

```bash
git commit -m "fix: retire r-series cfd route"
```
