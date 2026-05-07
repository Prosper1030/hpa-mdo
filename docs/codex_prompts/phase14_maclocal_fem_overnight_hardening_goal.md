# Phase 14 Mac-Local FEM Overnight Hardening Goal

這份 prompt 是給 Goal mode / long-running Codex worker 使用的自包含任務書。
預期 worker 可以使用 GPT-5.5、xhigh effort，連續工作 4 到 8 小時。

這不是 APDL 任務。Windows / APDL 可能整晚更新，暫時不可用。
本任務的目標是利用 Mac mini 上已經可跑的 Gmsh + CalculiX，把 Phase 14 的 Mac-local shell FEM 從「smoke / diagnostic」往「可比較、可收斂、可解釋」推進。

核心精神：

- 不要等待 Windows。
- 不要再只是讓 B1-B5 表格 pass。
- 要像結構工程師一樣反覆檢查：load、boundary condition、shell thickness、torsion loading、twist measurement、mesh convergence。
- 先驗證最簡單的 constant tube shell FEM，再回到 B2 tapered tube 和 B5 torsion。
- 如果找不到可信方法，要明確說「Mac-local shell FEM 仍不能當 truth」，不要硬凹 pass。

---

## Short Prompt To Paste Into Goal Mode

請讀並執行：

`docs/codex_prompts/phase14_maclocal_fem_overnight_hardening_goal.md`

這是一個 4 到 8 小時的 overnight structural FEM hardening 任務。Windows APDL 暫時不可用，所以請不要等 APDL。請用 Mac-local Gmsh + CalculiX 反覆改進 Phase 14 shell FEM：先建立 constant tube bending/torsion shell verification，對上材料力學閉式解後，再處理 B2 tapered tube shell convergence 和 B5 shell torsion load/twist measurement。你要自己查本地 manual / repo docs / 必要時官方文件，找出合理的 shell boundary/load/measurement 方法。不要改 aerodynamic ranking、hard gates、dual_beam_production production physics，不要加 calibration factor。完成後照 AGENTS.md 分任務 commit，最後用工程語言回報哪些 FEM 結果可信、哪些仍只是 diagnostic。

---

## Workspace

Repository:

```text
/Volumes/Samsung SSD/hpa-mdo
```

Primary config:

```text
configs/blackcat_004.yaml
```

Current important files:

```text
scripts/phase14_maclocal_fem_package.py
tests/test_phase14_maclocal_fem_package.py
scripts/phase14_calculix_beam_benchmarks.py
scripts/phase14_calculix_solution_hunt.py
src/hpa_mdo/hifi/calculix_runner.py
src/hpa_mdo/hifi/frd_parser.py
src/hpa_mdo/hifi/gmsh_runner.py
src/hpa_mdo/structure/calculix_beam_export.py
docs/calculix_parity_gate.md
docs/hi_fidelity_validation_stack.md
docs/Manual/ccx_2.22.pdf
```

Current relevant outputs:

```text
output/phase14_dual_beam_calibration/phase14_maclocal_fem_summary.md
output/phase14_dual_beam_calibration/b2_shell_fem_convergence.csv
output/phase14_dual_beam_calibration/b5_torsion_fem.csv
output/phase14_dual_beam_calibration/round4_solution_hunt_summary.md
output/phase14_dual_beam_calibration/b2_solution_hunt.md
output/phase14_dual_beam_calibration/b5_solution_hunt.md
```

Current known state:

```text
B2 shell FEM fine tip UZ = -0.139717 m
B2 internal beam tip UZ = -0.179741 m
B2 CalculiX B32R PIPE tip UZ = -0.160448 m
B2 shell-vs-B32R error = 12.921%
B2 shell-vs-internal error = 22.268%
B2 shell mesh is not convergence-quality yet

B5 shell torsion theta = 0.010833 rad
B5 theory theta = T L / GJ = 0.046792 rad
B5 shell torsion theta error = 76.848%
B5 B32R PIPE section-force torque = 99.9994 N m for 100 N m applied
B5 SECTION FORCES route is good for torque load ownership
B5 shell torsion route is not trustworthy yet
```

---

## Dirty Worktree Warning

Before starting, run:

```bash
git status --short
```

The user may have copied or moved the APDL package while preparing the Windows machine. If `output/phase14_dual_beam_calibration/apdl_windows_package/*` appears deleted or dirty, do not restore, delete, or commit those changes unless the user explicitly asks. Treat those as user-owned workspace changes.

Stage only files related to this overnight FEM hardening task.

---

## Hard Constraints

Do not do these things:

1. Do not change aerodynamic ranking.
2. Do not change hard gates.
3. Do not change `dual_beam_production` production physics.
4. Do not add arbitrary calibration factors.
5. Do not tune EI/GJ just to make plots look better.
6. Do not claim shell FEM is high-fidelity truth unless constant benchmarks pass and mesh convergence is demonstrated.
7. Do not run broad aero optimization.
8. Do not implement ASWING-like nonlinear behavior.
9. Do not depend on Windows/APDL being available.
10. Do not commit unrelated `output/` deletions.

Allowed:

1. Improve `scripts/phase14_maclocal_fem_package.py`.
2. Add helper functions for shell mesh generation, load application, twist measurement, convergence classification.
3. Add tests.
4. Add diagnostic scripts if the existing script becomes too large.
5. Add/update docs that explain trust boundaries.
6. Generate local outputs under `output/phase14_dual_beam_calibration/`.
7. Read local CalculiX/Gmsh manuals and repo high-fidelity docs.

---

## Engineering Mindset

You are acting as a structural verification engineer.

The current shell FEM problem is not just a coding problem. You must check physical meaning:

1. Is shell thickness represented correctly?
2. Are shell normals consistent?
3. Is the root clamp physically equivalent to the beam root clamp?
4. Is the tip/load ring constrained in a way that creates artificial stiffness?
5. Are loads applied as distributed loads, nodal forces, pressure, or equivalent ring forces?
6. Does the applied force/moment sum to the intended total?
7. Does reaction force/moment close equilibrium?
8. Does mesh refinement move the answer toward a stable value?
9. Is twist measured from a whole end ring or from a single noisy node?
10. Does a simple constant tube match hand calculation before using tapered geometry?

Use simple formulas:

```text
Cantilever tip load:
delta_tip = P L^3 / (3 E I)

Cantilever uniform load:
delta_tip = q L^4 / (8 E I)

Tube torsion:
theta_tip = T L / (G J)
G = E / (2 (1 + nu))
J = pi/2 * (R^4 - r^4)
```

---

## Required Start-Up Commands

Run:

```bash
git status --short
git log --oneline -10
./.venv/bin/python -m pytest tests/test_phase14_maclocal_fem_package.py tests/test_phase14_calculix_solution_hunt.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
./.venv/bin/python scripts/phase14_maclocal_fem_package.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration
```

If the script has different CLI arguments, inspect `--help` and run the equivalent command. Record the exact command used.

Read:

```text
output/phase14_dual_beam_calibration/phase14_maclocal_fem_summary.md
output/phase14_dual_beam_calibration/b2_shell_fem_convergence.csv
output/phase14_dual_beam_calibration/b5_torsion_fem.csv
docs/hi_fidelity_validation_stack.md
docs/calculix_parity_gate.md
```

---

## Task A: Build Constant Tube Shell Verification Ladder

### Why this comes first

Do not start by trying to fix tapered B2. A tapered shell problem has too many moving parts.

First prove that the shell FEM route can solve a constant circular tube:

1. constant tube bending
2. constant tube torsion
3. mesh convergence
4. force/moment equilibrium

### Required cases

Create controlled shell FEM cases:

```text
A1_constant_tube_tip_load
A2_constant_tube_uniform_load
A3_constant_tube_tip_torque
```

Use the same material scale as Phase 14:

```text
E = current Phase 14 material E
nu = current Phase 14 material nu
rho = current Phase 14 material density
outer radius = 0.03 m unless there is a better current benchmark value
thickness = 0.0015 m unless there is a better current benchmark value
span = 10 m
```

### Mesh families

Run at least:

```text
coarse
medium
fine
```

If feasible overnight and memory stays reasonable, add:

```text
extra_fine
```

Suggested shell mesh scale:

```text
coarse: 32 span x 32 circumference
medium: 64 x 64
fine: 96 x 96
extra_fine: 128 x 128 or smaller if Mac-safe
```

Do not exceed a level that causes swap/deadlock. If a mesh is too expensive, skip with a written reason and continue.

### Required outputs

Generate:

```text
output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_bending.csv
output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_bending.md
output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_torsion.csv
output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_torsion.md
```

Columns should include:

```text
case_id
mesh_id
n_span
n_circumference
element_count
load_or_torque
theory_value
fem_value
error_pct
reaction_or_moment_residual
mesh_delta_vs_previous_pct
mesh_delta_vs_finest_pct
max_von_mises_pa
status
engineering_note
```

### Acceptance

Constant tube bending/torsion should be treated as:

```text
PASS: closed-form error <= 5% and mesh_delta_vs_finest <= 5%
WARN: closed-form error <= 10% or convergence trend is monotonic but not yet tight
FAIL: wrong sign, bad equilibrium, or error stays large without explanation
```

If constant tube shell does not pass, do not call B2/B5 shell FEM high-fidelity.

### Commit

After Task A, commit only related files:

```bash
git add -p scripts/phase14_maclocal_fem_package.py tests/test_phase14_maclocal_fem_package.py
git commit -m "feat: add Phase 14 constant tube shell FEM verification"
```

If you add docs, include them in the same commit only if they document this task.

---

## Task B: Fix B5 Shell Torsion Load And Twist Measurement

### Current problem

Current B5 shell torsion is bad:

```text
theta_shell = 0.010833 rad
theta_theory = 0.046792 rad
error = 76.848%
```

That likely means the shell torsion load, boundary, cap behavior, or twist measurement is wrong.

### Required investigation

Try physically meaningful variants:

1. End-ring tangential force distribution.
2. Tip reference node with rigid/equation coupling to the end ring, if feasible.
3. Root ring clamp versus root cap clamp.
4. Twist measured by least-squares rotation of the whole tip ring.
5. Twist measured by angular displacement around the tube, not single node UZ.
6. Check total applied torque from nodal forces:

   ```text
   T_y = sum(z_i * F_x_i - x_i * F_z_i)
   ```

7. Check reaction moment if available.

### Twist measurement requirement

Do not rely on one point displacement for torsion.

Implement a ring-based twist estimator:

```text
theta = average angular change of all tip-ring nodes around the tube axis
```

or a least-squares rigid rotation estimate from undeformed to deformed tip ring coordinates.

Add unit tests for the estimator:

```text
known circular ring rotated by theta -> estimator returns theta
known pure translation -> estimator returns near zero
known noisy small rotation -> estimator remains stable
```

### Required outputs

Generate:

```text
output/phase14_dual_beam_calibration/maclocal_fem_hardening/b5_shell_torsion_hardening.csv
output/phase14_dual_beam_calibration/maclocal_fem_hardening/b5_shell_torsion_hardening.md
```

Columns:

```text
variant
mesh_id
n_span
n_circumference
applied_torque_n_m
recovered_torque_n_m
theory_theta_rad
shell_theta_rad
theta_error_pct
mesh_delta_vs_previous_pct
max_von_mises_pa
status
engineering_note
```

### Acceptance

Best outcome:

```text
B5 shell torsion error <= 5-10%
mesh convergence <= 5%
applied torque and reaction torque close
```

Acceptable outcome:

```text
The old bad shell torsion route is diagnosed.
A better load/measurement method is implemented.
Remaining error has a clear physical explanation.
```

Unacceptable:

```text
Continue reporting B5 shell torsion from single-node UZ or a non-physical torque application.
```

### Commit

```bash
git add -p scripts/phase14_maclocal_fem_package.py tests/test_phase14_maclocal_fem_package.py
git commit -m "feat: harden Phase 14 shell torsion FEM"
```

---

## Task C: Rework B2 Tapered Tube Shell FEM Only After Constant Baselines

### Current problem

Current B2 shell FEM is directionally closer to B32R PIPE, but not convergence-quality:

```text
coarse tip UZ = -0.057 m
medium tip UZ = -0.114 m
fine tip UZ = -0.140 m
B32R PIPE = -0.160 m
internal beam = -0.180 m
```

This is not stable enough to call truth.

### Required variants

Only after Task A gives useful constant-tube evidence, revisit B2:

1. Current tapered shell route.
2. Root clamp variant:
   - clamp all root-ring DOFs
   - clamp root cap / reference node if feasible
3. Load application variant:
   - nodal vertical force distributed over shell nodes by tributary span
   - pressure-like or line-load equivalent if feasible
4. Tip deflection measurement:
   - average tip-ring vertical displacement
   - max/min tip-ring vertical displacement
   - centerline-equivalent tip displacement
5. Mesh convergence:
   - coarse / medium / fine
   - extra_fine if Mac-safe

### Required outputs

Generate:

```text
output/phase14_dual_beam_calibration/maclocal_fem_hardening/b2_tapered_shell_hardening.csv
output/phase14_dual_beam_calibration/maclocal_fem_hardening/b2_tapered_shell_hardening.md
```

Columns:

```text
variant
mesh_id
n_span
n_circumference
element_count
tip_uz_avg_m
tip_uz_min_m
tip_uz_max_m
root_reaction_fz_n
reaction_residual_n
max_von_mises_pa
error_vs_internal_pct
error_vs_b32r_pipe_pct
mesh_delta_vs_previous_pct
mesh_delta_vs_finest_pct
status
engineering_note
```

### Acceptance

Best outcome:

```text
B2 shell convergence <= 5%
and shell result explains whether internal or B32R PIPE is closer
```

Acceptable outcome:

```text
B2 still WARN, but now the reason is precise:
boundary/load/shell formulation/mesh density.
```

Unacceptable:

```text
Use the current fine value as truth while convergence remains poor.
```

### Commit

```bash
git add -p scripts/phase14_maclocal_fem_package.py tests/test_phase14_maclocal_fem_package.py
git commit -m "feat: harden B2 tapered shell FEM convergence"
```

---

## Task D: Add FEM Trust Policy And Overnight Summary

Update or create:

```text
docs/calculix_parity_gate.md
output/phase14_dual_beam_calibration/maclocal_fem_hardening/overnight_summary.md
```

The summary must use plain engineering categories:

```text
trusted daily gate
directional diagnostic
not trustworthy yet
APDL-required
```

Answer:

1. Does constant tube shell bending pass?
2. Does constant tube shell torsion pass?
3. Is B5 shell torsion fixed?
4. Is B2 tapered shell converged?
5. Does Mac-local FEM now support B2 truth, or is APDL still required?
6. Does Mac-local FEM now support B5 twist/GJ truth, or only torque ownership through section forces?
7. What should the user do tomorrow morning when Windows/APDL is available?

Do not overclaim. If shell FEM remains diagnostic, say so clearly.

### Commit

```bash
git add -p docs/calculix_parity_gate.md
git commit -m "docs: clarify Phase 14 Mac-local FEM trust policy"
```

Do not force-add ignored output summaries unless this repo already tracks those output files.

---

## Required Tests And Runs

At minimum run:

```bash
./.venv/bin/python -m pytest tests/test_phase14_maclocal_fem_package.py tests/test_phase14_calculix_solution_hunt.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
```

Run the hardening workflow. If you add a new CLI flag, use that. Example:

```bash
./.venv/bin/python scripts/phase14_maclocal_fem_package.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration --task hardening
```

If the script does not support `--task`, implement a clear CLI.

Use resumable output. If one mesh level fails, write a partial row and continue with the next physically meaningful case.

---

## Runtime Guidance

This is an overnight task. It is okay to run longer than previous goals, but do not make the Mac unusable.

Guidelines:

1. Prefer many controlled small runs over one giant run.
2. Save intermediate CSV/MD after every case family.
3. If an extra-fine mesh takes too long, skip it with a reason.
4. If a variant clearly violates equilibrium, stop that variant and diagnose instead of refining it.
5. If you need official docs, use local manuals first. If local manuals are insufficient, search official Gmsh/CalculiX documentation or reputable solver references and cite what you used in the report.

---

## Final Response Format

Final response must include:

```text
Commits:
- <hash> <message>

Verification:
- <command> -> <result>

Constant tube shell:
- bending: PASS/WARN/FAIL, key error/convergence numbers
- torsion: PASS/WARN/FAIL, key error/convergence numbers

B5 shell torsion:
- fixed / improved / still bad
- theta theory, theta FEM, error
- torque equilibrium status

B2 tapered shell:
- converged / not converged
- shell tip UZ
- comparison to internal and B32R PIPE

Trust policy:
- trusted daily gate:
- directional diagnostic:
- not trustworthy yet:
- APDL-required:

Tomorrow APDL:
- exact file/folder the user should run if Windows is ready
```

Do not use vague wording like "looks reasonable" without numbers.

---

## Stop Conditions

Stop and report instead of forcing a fake pass if:

1. Constant tube shell bending cannot match closed form.
2. Constant tube shell torsion cannot match `T L / GJ`.
3. B5 torsion remains bad after physically meaningful torque and twist measurement variants.
4. B2 tapered shell remains non-converged after reasonable mesh refinement.
5. Fixing the route requires changing production physics.
6. Mac memory/time makes the next mesh level impractical.

In those cases, the deliverable is a clean diagnosis and trust policy, not a pass.

---

## Desired Outcome

Best possible outcome:

```text
Constant tube shell bending passes.
Constant tube shell torsion passes.
B5 shell torsion is fixed or clearly diagnosed.
B2 tapered shell has a useful convergence trend and no longer looks like random mesh noise.
Mac-local FEM earns a bounded, clearly stated role.
APDL remains final external truth for B2 and any remaining B5 twist/GJ question.
```

Minimum acceptable outcome:

```text
The shell FEM failure modes are no longer vague.
The route has constant-tube verification cases.
B2/B5 shell FEM are classified honestly.
The next APDL morning workflow remains ready.
```
