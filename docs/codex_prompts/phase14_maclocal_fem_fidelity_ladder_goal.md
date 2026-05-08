# Phase 14 Mac-Local FEM Fidelity Ladder Goal

這份 prompt 是給 Goal mode / long-running Codex worker 使用的自包含任務書。
預期 worker 可以使用 GPT-5.5、xhigh effort，連續工作 6 到 10 小時。

這不是 Windows/APDL 任務，也不是 aero optimization 任務。

本任務的核心問題是：

```text
我們現在到底應該用哪一種 Mac-local structural FEM，來驗證 CFRP tube / double-beam model？

1. CalculiX beam element route
2. structured shell route
3. 3D solid / volume FEM route
```

上一輪已經證明 structured S4 shell 比 legacy triangular shell 好很多，但是 constant tube 仍穩定偏硬約 6-7%。所以現在不要再只加更多 B2/B5 表格，而是要建立一條清楚的 fidelity ladder：用材料力學閉式解當地基，逐步比較 beam / shell / solid 的 accuracy、runtime、mesh convergence、以及對 tubing model 的工程價值。

---

## Short Prompt To Paste Into Goal Mode

請讀並執行：

`docs/codex_prompts/phase14_maclocal_fem_fidelity_ladder_goal.md`

這是一個 6 到 10 小時的 Mac-local structural FEM fidelity-ladder 任務。不要等 Windows/APDL，也不要做 aero optimization。請比較 CalculiX beam、structured shell、3D solid/volume FEM 三條路線，判斷哪一種最適合拿來驗證 CFRP tubing / dual-beam model。重點不是讓更多 case pass，而是用材料力學閉式解、mesh convergence、runtime、reaction closure、torsion/bending error，找出 shell 目前穩定偏硬 6-7% 的原因，並嘗試建立 solid FEM 對照。請用結構工程角度判斷，不准把「solid 比 shell 高保真」當成未證明假設；thin-wall tube 的 solid mesh 如果厚度方向不夠，可能反而不準。不要改 aerodynamic ranking、hard gates、dual_beam_production production physics，也不要加 calibration factor。完成後分任務 commit，最後給出 beam/shell/solid 的 trust policy 和下一步 APDL 使用建議。

---

## Plain-Language Context

使用者不是 mechanical 背景，所以 final report 要用會一點材料力學的人能懂的方式寫。

請把名詞講清楚：

- FEM = finite element method，結構分析主要用這個。
- FVM = finite volume method，通常是 CFD 用語；這裡不要把結構 CalculiX 叫 FVM。
- beam model = 把 tube 當成一條梁，只看整體彎曲/扭轉，速度最快。
- shell model = 把 tube wall 當成薄殼面，適合 thin-wall tube，能看局部壁面應力和一些 buckling 診斷。
- solid / volume FEM = 用 3D 體元素填出管壁厚度，理論上更接近 3D continuum，但 thin-wall tube 必須有足夠厚度方向網格；如果只有一層差的 tetra/hex，可能比 shell 更假硬或更假軟。

不要直接說 solid 一定最高保真。要用 benchmark 證明。

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

Key current files:

```text
scripts/phase14_maclocal_fem_package.py
tests/test_phase14_maclocal_fem_package.py
scripts/phase14_calculix_beam_benchmarks.py
src/hpa_mdo/hifi/calculix_runner.py
src/hpa_mdo/hifi/frd_parser.py
src/hpa_mdo/hifi/gmsh_runner.py
src/hpa_mdo/structure/calculix_beam_export.py
docs/calculix_parity_gate.md
docs/hi_fidelity_validation_stack.md
docs/Manual/ccx_2.22.pdf
```

Current important outputs:

```text
output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_bending.md
output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_torsion.md
output/phase14_dual_beam_calibration/maclocal_fem_hardening/b2_tapered_shell_hardening.md
output/phase14_dual_beam_calibration/maclocal_fem_hardening/b5_shell_torsion_hardening.md
output/phase14_dual_beam_calibration/maclocal_fem_hardening/overnight_summary.md
```

Current known state from last run:

```text
Constant tube bending:
- fine tip load shell: -0.911266 m vs theory -0.982509 m, error 7.251%
- fine uniform load shell: -0.346407 m vs theory -0.368441 m, error 5.980%

Constant tube torsion:
- fine structured S4 theta: 0.0434057 rad vs theory 0.0467920 rad, error 7.237%

B5 shell torsion:
- legacy Gmsh triangular route: 76.849% theta error, not trustworthy
- structured S4 ring torque route: 7.237% theta error, useful diagnostic but not final truth

B2 tapered shell:
- structured S4 fine tip UZ: -0.171790 m
- internal beam tip UZ: -0.179741 m, shell-vs-internal error 4.424%
- B32R PIPE tip UZ: -0.160448 m, shell-vs-B32R error 7.069%
```

---

## Dirty Worktree Warning

Before starting, run:

```bash
git status --short
```

The user may have copied or moved the APDL package while preparing the Windows machine. If `output/phase14_dual_beam_calibration/apdl_windows_package/*` appears deleted or dirty, do not restore, delete, stage, or commit those changes unless the user explicitly asks.

Stage only files related to this fidelity-ladder task.

---

## Hard Constraints

Do not:

1. Do not change aerodynamic ranking.
2. Do not change hard gates.
3. Do not change `dual_beam_production` production physics.
4. Do not add EI/GJ calibration factors just to match FEM.
5. Do not run broad aero optimization.
6. Do not implement nonlinear / ASWING-like behavior.
7. Do not claim shell or solid FEM is truth until constant benchmarks and convergence support it.
8. Do not treat solid FEM as automatically more accurate than shell FEM.
9. Do not commit the user-owned APDL package deletion.

Allowed:

1. Add a new `--task fidelity-ladder` CLI path or a new diagnostic script if cleaner.
2. Add beam/shell/solid comparison helpers.
3. Add tests for generated deck sanity, mesh metadata, twist/deflection estimators, and report classification.
4. Add docs and output reports.
5. Read local manuals and repo docs. If needed, search official CalculiX/Gmsh documentation and cite sources in the report.

---

## Engineering Question To Answer

Answer this in engineering terms:

```text
For the CFRP tubing / dual-beam problem, what should be our Mac-local verification hierarchy?

Example possible answer:

1. Beam-FEM: daily global deflection/reaction/torsion ownership check.
2. Structured shell FEM: thin-wall tube wall stress and diagnostic check, if constant benchmark bias is understood.
3. Solid FEM: local joint / root / thick-wall detail check only if mesh quality and thickness resolution are demonstrated.
4. APDL: final external check for B2 tapered truth and B5 twist/GJ truth.
```

Do not decide this by taste. Decide it by running controlled comparisons.

---

## Task A: Audit Current FEM Routes And Runtime

Run the existing tests and current hardening workflow:

```bash
./.venv/bin/python -m pytest tests/test_phase14_maclocal_fem_package.py tests/test_phase14_calculix_solution_hunt.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
./.venv/bin/python scripts/phase14_maclocal_fem_package.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration --task hardening
```

Record wall time for:

```text
beam parity run
structured shell constant tube run
B2 structured shell run
B5 shell torsion run
```

If exact wall time is hard to get, use Python `time.perf_counter()` or shell `time`.

Output:

```text
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/current_route_audit.md
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/runtime_summary.csv
```

Commit:

```bash
git add -p scripts/phase14_maclocal_fem_package.py tests/test_phase14_maclocal_fem_package.py docs/calculix_parity_gate.md
git commit -m "feat: audit Phase 14 Mac-local FEM route runtime"
```

If Task A only writes ignored output files and no tracked source/docs changed, do not force a commit.

---

## Task B: Explain Or Reduce The Structured Shell 6-7% Stiffness Bias

Current structured shell is stable but too stiff by about 6-7%.

Investigate physically meaningful causes:

1. Shell section thickness interpretation.
2. Radius convention:
   - is the mesh at mid-surface radius?
   - is theory using outer radius / inner radius / mid-surface radius consistently?
3. Beam closed-form section properties:
   - compare exact tube `I` and `J`
   - compare thin-wall approximation only as a diagnostic, not truth
4. Root clamp effect:
   - root ring clamp
   - short rigid cap
   - reference-node coupling if feasible
5. Load application effect:
   - end ring equal forces
   - distributed face/edge equivalent load
   - avoid artificial tip cap stiffness unless testing it explicitly
6. Element formulation:
   - existing structured S4
   - check whether CalculiX supports a usable S8/S8R or other second-order shell in this context
   - if unsupported or parser cannot read it, document that cleanly
7. Length/radius/thickness sensitivity:
   - run at least one longer tube or smaller load to see if the bias is formulation or geometry-dependent

Do not blindly tune thickness or material.

Output:

```text
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/shell_bias_diagnosis.csv
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/shell_bias_diagnosis.md
```

Required columns:

```text
variant
case_type
element_type
radius_convention
root_bc
load_method
n_span
n_circumference
element_count
theory_value
fem_value
error_pct
mesh_delta_pct
runtime_s
status
engineering_note
```

Acceptance:

```text
PASS: at least one physically valid shell route gets bending and torsion <= 5% vs closed form with stable convergence
WARN: best route remains 5-10%, but cause is narrowed to a clear modeling limitation
FAIL: shell route remains unexplained or equilibrium/load/root setup is suspect
```

Commit:

```bash
git add -p scripts/phase14_maclocal_fem_package.py tests/test_phase14_maclocal_fem_package.py docs/calculix_parity_gate.md
git commit -m "feat: diagnose Phase 14 structured shell FEM stiffness bias"
```

---

## Task C: Attempt A 3D Solid / Volume FEM Tube Route

This is the user's "not shell" route.

Goal:

```text
Build or prototype a 3D solid tube FEM route and compare it against the same constant tube bending/torsion closed-form checks.
```

Important engineering warning:

For thin-wall tube, solid FEM is not automatically better. It needs enough elements through thickness. A bad solid mesh can be more misleading than shell.

Preferred attempt order:

1. Structured hexahedral or swept volume tube if feasible.
2. At least 2 elements through thickness; 3 is better if runtime is acceptable.
3. If only tetrahedral mesh is feasible, clearly label it as tetra diagnostic and check whether it is too stiff in bending/torsion.
4. Use constant tube first, not B2.
5. Use the same root/load/twist measurement conventions as the shell route where possible.

CalculiX element candidates to investigate:

```text
C3D8 / C3D8R
C3D20 / C3D20R
C3D10
```

Do not assume all are supported by the current exporter/parser. If a candidate fails, write the exact solver/parser limitation and move to the next candidate.

Required cases:

```text
C1_solid_constant_tube_tip_load
C2_solid_constant_tube_uniform_load
C3_solid_constant_tube_tip_torque
```

Required mesh levels:

```text
coarse
medium
fine if Mac-safe
```

Required output:

```text
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/solid_tube_probe.csv
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/solid_tube_probe.md
```

Required columns:

```text
case_id
mesh_id
element_type
n_span
n_circumference
n_thickness
node_count
element_count
theory_value
fem_value
error_pct
reaction_residual
runtime_s
max_von_mises_pa
status
engineering_note
```

Acceptance:

```text
PASS: solid route beats or matches shell on bending and torsion with reasonable runtime and convergence
WARN: solid route runs but is not clearly better than shell, or needs too many elements through thickness
FAIL: solid route is solver-rejected, parser-blocked, too expensive, or physically worse than shell
```

Commit:

```bash
git add -p scripts/phase14_maclocal_fem_package.py tests/test_phase14_maclocal_fem_package.py
git commit -m "feat: add Phase 14 solid tube FEM probe"
```

---

## Task D: Compare Beam / Shell / Solid As A Fidelity Ladder

Create a single decision matrix:

```text
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/fidelity_ladder_comparison.csv
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/fidelity_ladder_decision.md
```

Rows:

```text
CalculiX B32R PIPE beam
internal equivalent/tubing beam
structured shell current best
solid/volume current best
legacy triangular shell
```

Compare:

```text
global bending accuracy
global torsion accuracy
reaction closure
runtime
mesh convergence behavior
thin-wall suitability
local stress usefulness
buckling usefulness
implementation maturity
Mac-local automation readiness
recommended role
```

Use plain categories:

```text
daily gate
design diagnostic
local detail probe
not recommended
APDL-required
```

Engineering rule:

```text
The recommended route should be the simplest model that is accurate enough for the quantity.
Do not choose a more complex model just because it sounds high-fidelity.
```

Commit:

```bash
git add -p docs/calculix_parity_gate.md
git commit -m "docs: define Phase 14 FEM fidelity ladder"
```

---

## Task E: Re-Run B2/B5 Only With The Best Route

After Tasks B-D, re-run B2 and B5 with only the best justified route:

```text
B2 tapered tube bending
B5 tube torsion / twist
```

Do not run every bad route again unless needed for comparison.

Output:

```text
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/b2_b5_best_route_check.csv
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/b2_b5_best_route_check.md
```

Answer:

1. Does the best Mac-local route support the internal tubing model within 5% for B2?
2. Does the best Mac-local route support B5 torsion/twist within 5-10%?
3. Is APDL still required?
4. Which APDL file should the user run tomorrow?

Commit:

```bash
git add -p scripts/phase14_maclocal_fem_package.py tests/test_phase14_maclocal_fem_package.py docs/calculix_parity_gate.md
git commit -m "feat: add Phase 14 best-route FEM check"
```

---

## Required Final Report

Write:

```text
output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/final_report.md
```

The final report must be readable by a non-mechanical specialist.

Use this structure:

```text
1. One-paragraph answer
2. Beam vs shell vs solid explanation
3. What passed
4. What stayed warning-level
5. Which route is fastest
6. Which route is most accurate for global deflection/twist
7. Which route is useful for local stress/buckling
8. What APDL still needs to answer
9. What to trust in the current tubing / dual-beam model
10. Exact next command/files
```

Must include numbers:

```text
tip deflection error %
torsion/twist error %
runtime seconds
mesh size
reaction residual
```

Do not use vague phrases like "looks good" without numbers.

---

## Required Tests

At minimum:

```bash
./.venv/bin/python -m pytest tests/test_phase14_maclocal_fem_package.py tests/test_phase14_calculix_solution_hunt.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
```

If you add a new parser/helper file, add targeted tests for it.

If a long FEM run is not suitable for pytest, test:

```text
deck generation
mesh metadata
load sum / torque reconstruction
twist estimator
CSV/report schema
classification logic
```

---

## Stop Conditions

Stop and report honestly if:

1. Solid FEM cannot be built safely on Mac within reasonable runtime.
2. CalculiX rejects the needed solid/shell elements.
3. Parser cannot read the needed displacement/stress outputs and fixing it becomes too large.
4. Shell bias remains 6-7% after meaningful variants.
5. A more complex route is slower and not more accurate than beam/shell.

In these cases, the deliverable is still useful: it tells us which route not to trust.

---

## Final Response Format

Final response must include:

```text
Commits:
- <hash> <message>

Verification:
- <command> -> <result>

Fidelity ladder:
- beam:
- shell:
- solid:

Best current Mac-local route:
- for global tube deflection:
- for torsion/twist:
- for local stress:
- for buckling:

Key numbers:
- constant bending:
- constant torsion:
- B2:
- B5:
- runtime:

Trust policy:
- trusted daily gate:
- directional diagnostic:
- not recommended:
- APDL-required:

Plain-language recommendation:
- <what the user should do next>
```

Keep it honest. A well-diagnosed WARN is better than a fake PASS.
