# Phase 14 CalculiX Beam Parity Round 3 Goal

這份 prompt 是給 Goal mode / long-running Codex worker 使用的自包含任務書。
預期 worker 可以使用 GPT-5.5、xhigh effort，連續工作 1 到 4 小時。

核心精神：

- 這不是只修兩個 software review findings。
- 這是一輪結構驗證任務：worker 必須用結構力學角度判斷 internal beam model、CalculiX beam-FEM、wire support、torque ownership 到底有沒有在解同一個物理問題。
- 可以寫 code、補 test、跑 CalculiX、寫報告、分 commit。
- 不可以改 aerodynamic ranking、hard gates，也不可以偷塞無物理意義的 calibration factor。

---

## Short Prompt To Paste Into Goal Mode

請讀並執行：

`docs/codex_prompts/phase14_calculix_parity_round3_goal.md`

你要把這當成一個 1 到 4 小時的結構驗證任務，不只是 coding task。請用結構工程師角度診斷 B2 tapered beam、B4 wire reaction、B5 torque ownership，必要時修 exporter/runner/tests/docs，但不要改 aerodynamic ranking、hard gates、dual_beam_production production physics、nonlinear/ASWING-like 行為。完成後請照 AGENTS.md 分任務 commit，最後回報測試、benchmark 結果、工程判讀與 commit hash。

---

## Workspace

Repository:

```text
/Volumes/Samsung SSD/hpa-mdo
```

Shell:

```text
zsh
```

Primary config:

```text
configs/blackcat_004.yaml
```

Current Mac-local solver route:

```text
load_config("configs/blackcat_004.yaml") + find_ccx(cfg)
```

Do not assume `which ccx` is the only solver discovery path. This repo may use `configs/local_paths.yaml` overlay locally, but that file is gitignored and must not be required by unit tests.

---

## Current State To Verify, Not Assume

Recent committed work reportedly added a Mac-local CalculiX linear beam-parity MVP.

Known files:

```text
src/hpa_mdo/structure/calculix_beam_export.py
scripts/phase14_calculix_beam_benchmarks.py
tests/test_phase14_calculix_beam_export.py
tests/test_phase14_calculix_beam_benchmarks.py
docs/calculix_parity_gate.md
```

Known local output directory:

```text
output/phase14_dual_beam_calibration/
```

Known current benchmark interpretation from the previous run:

| Case | Current status | Current interpretation |
|---|---:|---|
| B1 tip load | PASS | Closed-form vs CalculiX about 0.46%, internal vs CalculiX about 0.47% |
| B1 uniform load | PASS | Closed-form vs CalculiX about 0.53%, internal vs CalculiX about 0.62% |
| B2 tapered uniform load | WARN | Internal vs CalculiX about 10.7%; likely tapered EI / section interpolation mismatch |
| B3 dual beam lift only | PASS | Main/rear displacement parity about 2.3% |
| B4 vertical wire | WARN | Displacement parity acceptable, support reaction error about 18.8% |
| B5 torque variants | WARN | Current report does not truly measure torque parity |

You must reproduce the current state before changing anything.

---

## Hard Constraints

Do not do these things:

1. Do not change aerodynamic ranking.
2. Do not change hard gates.
3. Do not run broad aero optimization.
4. Do not silently change `dual_beam_production` production physics equations.
5. Do not add arbitrary fudge factors.
6. Do not add calibration factors unless every factor is physically explained and tied to a benchmark result.
7. Do not enable nonlinear geometry for this round.
8. Do not implement ASWING-like behavior in this round.
9. Do not convert this into a full shell/solid high-fidelity model.
10. Do not treat APDL as abandoned. APDL remains final external check.
11. Do not force-add ignored `output/` artifacts unless the repo already tracks that specific artifact or the user explicitly asks.
12. Do not claim B4 reaction truth or B5 torque truth unless the measured quantity actually supports that claim.

Allowed changes:

1. Fix tests.
2. Add benchmark diagnostic modes.
3. Improve CalculiX beam exporter if the change is physically justified.
4. Improve CalculiX `.dat` / `.frd` parsing.
5. Add CSV columns and markdown reports.
6. Add small benchmark helpers.
7. Update `docs/calculix_parity_gate.md`.
8. Add new tests around B2/B4/B5 diagnostics.
9. Generate local output reports under `output/phase14_dual_beam_calibration/`.

---

## Engineering Mindset Required

You are not only a coding worker. You are acting as a structural verification engineer.

For every mismatch, answer these questions:

1. Are the internal model and CalculiX solving the same boundary value problem?
2. Are node coordinates identical?
3. Are material values identical?
4. Are section properties identical?
5. Are loads applied at the same physical locations?
6. Are constraints equivalent?
7. Are rigid links and equation constraints changing reaction bookkeeping?
8. Does global force equilibrium close?
9. Does global moment equilibrium close when torque is present?
10. Does the result pass a simple hand-calculation sanity check?
11. Is the discrepancy likely a code bug, FEM deck convention, model-form difference, or physical definition mismatch?

Use elementary beam theory where possible:

```text
Cantilever tip load:
delta_tip = P L^3 / (3 E I)

Cantilever uniform load:
delta_tip = q L^4 / (8 E I)

Small-angle twist proxy for front/rear spar vertical displacement:
theta_proxy ~= (uz_rear - uz_main) / chordwise_spar_spacing

Basic vertical force equilibrium:
sum(Rz_supports) + sum(Fz_external) ~= 0
```

For tapered beams, do not blindly trust either solver. Compare compliance/integration conventions and mesh convergence.

---

## References To Read First

Read these files before implementing:

```text
docs/calculix_parity_gate.md
src/hpa_mdo/structure/calculix_beam_export.py
scripts/phase14_calculix_beam_benchmarks.py
tests/test_phase14_calculix_beam_export.py
tests/test_phase14_calculix_beam_benchmarks.py
src/hpa_mdo/hifi/calculix_runner.py
src/hpa_mdo/hifi/frd_parser.py
docs/codex_prompts/M_HF2_calculix_linear.md
```

Also inspect existing Phase 14 reports if present:

```text
output/phase14_dual_beam_calibration/comparison_summary.md
output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv
output/phase14_dual_beam_calibration/model_inventory.md
output/phase14_dual_beam_calibration/benchmark_manifest.csv
```

ASWING references may be read only for conceptual large-deflection / aeroelastic caution:

```text
docs/Manual/ASWING_Extended_User_Manual.pdf
docs/codex_prompts/M_ASWING_e2e_runner.md
docs/research/hi_fidelity_refs/大展弦比撓度機翼氣動彈性力學分析：Drela ASWING 核心架構與實作指南.md
```

ASWING is not part of this implementation round.

---

## Required Start-Up Commands

Run these before editing:

```bash
git status --short
git log --oneline -8
./.venv/bin/python -m pytest tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
./.venv/bin/python scripts/phase14_calculix_beam_benchmarks.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration/round3_baseline
```

If the benchmark runner cannot find `ccx`, diagnose through repo config:

```bash
./.venv/bin/python - <<'PY'
from hpa_mdo.config import load_config
from hpa_mdo.hifi.calculix_runner import find_ccx
from hpa_mdo.hifi.gmsh_runner import find_gmsh

cfg = load_config("configs/blackcat_004.yaml")
print("ccx:", find_ccx(cfg))
print("gmsh:", find_gmsh(cfg))
PY
```

Do not fail the whole task only because `which ccx` is empty.

---

## Review Findings To Address

### Finding 1: portable solver discovery test

Current issue:

```text
tests/test_phase14_calculix_beam_benchmarks.py:14-19
```

The test depends on `configs/local_paths.yaml`, which is gitignored and only exists on this Mac. A clean checkout or CI machine without the local overlay may fail even if skip-path behavior is valid.

Required fix:

- Make the positive solver discovery test portable.
- Prefer one of these:
  - create a temporary `local_paths.yaml` fixture and pass it through the config loader if supported
  - monkeypatch `find_ccx` / `find_gmsh` for the positive discovery case
  - split real Mac solver availability into an integration smoke path that can skip cleanly
- Keep normal production runner behavior unchanged.

Acceptance:

- Unit tests do not require the user's private `configs/local_paths.yaml`.
- Real Mac-local discovery still works when local config exists.
- CI/clean checkout can run the test file without local solver paths.

### Finding 2: B5 does not yet measure torque parity

Current issue:

```text
scripts/phase14_calculix_beam_benchmarks.py:704-715
```

The B5 report currently decides from vertical tip deflections and total RF only. In actual outputs, `main_beam_my_about_main_spar` and `cm_off_control` produce identical UZ/reaction rows, so B5 is not really validating MY torque ownership.

Required fix:

- Add a true torque-sensitive diagnostic.
- Preferred order:
  1. Parse beam rotations from CalculiX output if available and reliable.
  2. If rotations are not available, compute a displacement-derived twist proxy:

     ```text
     twist_proxy_rad = (rear_tip_uz - main_tip_uz) / chordwise_spar_spacing
     ```

  3. If possible, also add moment-reaction or force-couple diagnostics.
- The B5 report must say whether torque changed the response, not just whether vertical bending moved.

Acceptance:

- B5 CSV/report includes a torque-sensitive quantity.
- B5 modes can distinguish `cm_off_control` from actual torque application if the deck applies torque.
- If CalculiX output cannot expose true rotations/moments yet, document that B5 remains report-only and explain the missing measurement.

---

## Main Deliverable

By the end of this Goal run, the repo should have a stronger Mac-local CalculiX beam parity gate with:

1. Portable tests.
2. Better B2 tapered-beam diagnosis.
3. Better B4 wire reaction bookkeeping diagnosis.
4. A real B5 torque/twist diagnostic.
5. Updated docs that prevent future agents from overclaiming the results.
6. Clear local output reports under:

```text
output/phase14_dual_beam_calibration/
```

---

## Task A: Baseline Reproduction And Audit

### Files to inspect

```text
src/hpa_mdo/structure/calculix_beam_export.py
scripts/phase14_calculix_beam_benchmarks.py
tests/test_phase14_calculix_beam_export.py
tests/test_phase14_calculix_beam_benchmarks.py
docs/calculix_parity_gate.md
```

### Required work

1. Confirm git state is clean or document unrelated dirty files.
2. Run the startup tests.
3. Run the benchmark into:

   ```text
   output/phase14_dual_beam_calibration/round3_baseline/
   ```

4. Inspect:

   ```text
   output/phase14_dual_beam_calibration/comparison_summary.md
   output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv
   ```

5. Summarize whether current numbers match the expected B1/B2/B3/B4/B5 status.

### Acceptance

- You know the current checkout behavior before editing.
- You can distinguish existing failures from failures introduced by your edits.

---

## Task B: Make Solver Discovery Tests Portable

### Files likely to modify

```text
tests/test_phase14_calculix_beam_benchmarks.py
```

Potentially inspect:

```text
src/hpa_mdo/config.py
src/hpa_mdo/hifi/calculix_runner.py
src/hpa_mdo/hifi/gmsh_runner.py
```

### Required work

1. Identify the test that assumes local private solver paths.
2. Replace that assumption with deterministic test setup.
3. Keep a separate skip-friendly real-solver smoke only if useful.
4. Run:

   ```bash
   ./.venv/bin/python -m pytest tests/test_phase14_calculix_beam_benchmarks.py -q
   ```

### Acceptance

- Test passes without relying on private machine config.
- Test still proves the intended discovery behavior.

### Commit

After this task:

```bash
git add -p tests/test_phase14_calculix_beam_benchmarks.py
git commit -m "test: make CalculiX solver discovery benchmark test portable"
```

If `git add -p` cannot run in this environment, stage only the exact related file path and explain that in the final response.

---

## Task C: B2 Tapered Beam Structural Diagnosis

### Problem

B1 constant-section cantilever cases pass, but B2 tapered uniform-load case has about 10.7% internal-vs-CalculiX mismatch.

That strongly suggests:

- basic units are probably okay
- root clamp is probably okay
- constant pipe section syntax is probably okay
- distributed load mapping is probably close
- tapered section interpretation remains suspicious

### Files likely to modify

```text
scripts/phase14_calculix_beam_benchmarks.py
src/hpa_mdo/structure/calculix_beam_export.py
tests/test_phase14_calculix_beam_benchmarks.py
tests/test_phase14_calculix_beam_export.py
```

### Diagnostic variants to implement or generate

Create a B2 diagnosis sweep that compares these cases:

1. Constant-section control using the same B2 code path.
2. Tapered section using current exporter behavior.
3. Tapered section with midpoint sampling.
4. Tapered section with inboard/end sampling.
5. Tapered section with outboard/end sampling.
6. Tapered section with physically averaged per-element properties if appropriate.
7. Mesh refinement sweep:

   ```text
   n_elem = 8, 16, 32, 64, 128
   ```

8. Load discretization sensitivity:

   ```text
   equivalent nodal loads vs existing distributed/nodal mapping
   ```

9. Element type sensitivity if current exporter can support it without destabilizing the route:

   ```text
   B31 / B32 / B32R
   ```

Do not implement a large abstraction only for this sweep. A focused helper inside the benchmark script is acceptable if it stays readable.

### Quantities to report

For every variant:

```text
case_id
variant
n_elem
element_type
section_sampling_mode
internal_tip_uz_m
calculix_tip_uz_m
closed_form_or_reference_tip_uz_m
internal_vs_calculix_error_pct
reference_vs_calculix_error_pct
root_reaction_fz_n
reaction_residual_n
engineering_note
```

### Independent reference requirement

For tapered B2, add at least one independent beam-theory reference that is not simply the current internal result copied again.

Acceptable options:

1. Numerical Euler-Bernoulli compliance integration:

   ```text
   EI(y) from tube geometry
   curvature(y) = M(y) / EI(y)
   integrate curvature twice with clamp boundary conditions
   ```

2. Dense finite-difference beam reference.
3. Dense element transfer-matrix reference.
4. If an existing internal helper already does this cleanly, use it only after explaining why it is independent enough.

### Engineering questions to answer

1. Does the error converge away with mesh refinement?
2. Does CalculiX converge to a stable answer different from internal?
3. Does a different section sampling convention explain most of the gap?
4. Is the internal model using station properties while CalculiX uses element properties?
5. Is the mismatch caused by `I` interpolation rather than radius/thickness interpolation?
6. Is shear deformation relevant at this span/slenderness, or is Euler-Bernoulli enough?
7. Which convention is physically best for tapered tube beam parity?

### Outputs

Generate:

```text
output/phase14_dual_beam_calibration/b2_taper_diagnosis.csv
output/phase14_dual_beam_calibration/b2_taper_diagnosis.md
```

### Acceptance

One of these must be true:

1. B2 error is reduced to less than or equal to 2% by a physically justified exporter/benchmark fix.
2. B2 remains WARN, but the diagnosis clearly identifies the likely source and next action.

Do not hide a 10% mismatch by changing tolerance.

### Commit

After this task:

```bash
git add -p src/hpa_mdo/structure/calculix_beam_export.py scripts/phase14_calculix_beam_benchmarks.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py
git commit -m "feat: diagnose CalculiX tapered beam parity"
```

If the actual change is a clear bug fix rather than a diagnostic feature, use:

```bash
git commit -m "fix: align CalculiX tapered beam section sampling"
```

---

## Task D: B4 Wire Reaction Bookkeeping Diagnosis

### Problem

B4 vertical-wire case has acceptable displacement parity, but reaction error is around 18.8%.

Current suspicion:

- The vertical wire surrogate is kinematically useful.
- The current reaction metric may not measure physical support reaction correctly.
- CalculiX support reactions may be affected by constrained-node loads, equation constraints, rigid links, or MPC dependency choices.

### Files likely to modify

```text
scripts/phase14_calculix_beam_benchmarks.py
src/hpa_mdo/structure/calculix_beam_export.py
tests/test_phase14_calculix_beam_benchmarks.py
```

Potentially inspect:

```text
src/hpa_mdo/hifi/frd_parser.py
```

### Diagnostic variants to implement or generate

Create B4 diagnostic cases:

1. Root fixed only, no wire.
2. Root fixed plus one vertical wire constraint, no rigid links.
3. Root fixed plus vertical wire plus rigid links.
4. Wire node carries no applied load; redistribute nearby load to adjacent unconstrained nodes.
5. Wire node carries applied load; report constrained-node load separately.
6. Main wire node and link node colocated.
7. Main wire node not coincident with link node if geometry allows a controlled variant.

### Quantities to parse/report

For every variant:

```text
case_id
variant
main_tip_uz_m
rear_tip_uz_m
max_uz_m
applied_total_fz_n
applied_fz_on_root_nodes_n
applied_fz_on_wire_nodes_n
root_reaction_fz_raw_n
wire_reaction_fz_raw_n
all_support_reaction_fz_raw_n
all_support_reaction_fz_corrected_n
reaction_residual_raw_n
reaction_residual_corrected_n
internal_wire_reaction_fz_n
internal_root_reaction_fz_n
wire_reaction_error_pct
root_reaction_error_pct
engineering_note
```

### Required structural checks

For each B4 variant, answer:

1. Does `sum(Rz) + sum(Fz)` close?
2. Are loads applied directly on constrained nodes?
3. If yes, does CalculiX report support reaction before or after subtracting constrained-node applied load?
4. Are equation constraints hiding reaction in dependent DOFs?
5. Does reversing equation dependency change reported RF without changing kinematics?
6. Is the current support group `HPA_SUPPORT_ALL` physically meaningful?
7. Should root and wire support be reported separately?

### Outputs

Generate:

```text
output/phase14_dual_beam_calibration/b4_wire_reaction_diagnosis.csv
output/phase14_dual_beam_calibration/b4_wire_reaction_diagnosis.md
```

### Acceptance

One of these must be true:

1. Root/wire reactions are recovered in a physically meaningful way and match target tolerance.
2. B4 remains kinematic parity only, and the report explicitly says reaction truth is not yet established.

Do not call B4 reaction validated if vertical equilibrium does not close.

### Commit

After this task:

```bash
git add -p src/hpa_mdo/structure/calculix_beam_export.py scripts/phase14_calculix_beam_benchmarks.py tests/test_phase14_calculix_beam_benchmarks.py
git commit -m "feat: add CalculiX wire reaction diagnostics"
```

---

## Task E: B5 Torque Ownership Diagnostic

### Problem

B5 currently does not prove torque parity. It mainly reports vertical tip displacement and total reaction. That is insufficient because a pitching moment may primarily show up as twist/front-rear differential displacement, not total vertical bending.

### Files likely to modify

```text
scripts/phase14_calculix_beam_benchmarks.py
src/hpa_mdo/structure/calculix_beam_export.py
tests/test_phase14_calculix_beam_benchmarks.py
```

Potentially inspect:

```text
src/hpa_mdo/hifi/frd_parser.py
```

### B5 modes to preserve

Keep these modes:

```text
main_beam_my_about_main_spar
front_rear_vertical_couple
cm_off_control
```

Do not rename them unless every report and test is updated.

### Required diagnostic metrics

For every B5 mode, report:

```text
case_id
torque_mode
main_tip_uz_m
rear_tip_uz_m
rear_minus_main_tip_uz_m
chordwise_spar_spacing_m
twist_proxy_rad
twist_proxy_deg
root_reaction_fz_n
wire_reaction_fz_n
moment_or_couple_diagnostic_n_m
internal_twist_proxy_rad
calculix_twist_proxy_rad
twist_error_pct
engineering_note
```

### Preferred implementation path

1. First inspect whether CalculiX beam rotation output is available in current `.frd` or `.dat`.
2. If direct rotation output is available and parseable, add parser support and tests.
3. If direct rotation output is not available, implement the displacement-derived twist proxy:

   ```text
   twist_proxy_rad = (rear_tip_uz - main_tip_uz) / chordwise_spar_spacing
   twist_proxy_deg = twist_proxy_rad * 180 / pi
   ```

4. Check whether the moment mode changes `twist_proxy_rad`.
5. Check whether `cm_off_control` stays near the expected zero-torque baseline.
6. Check whether `front_rear_vertical_couple` gives a larger front/rear differential response than `cm_off_control`.

### Structural sanity checks

Answer:

1. If `main_beam_my_about_main_spar` and `cm_off_control` still produce identical response, is the torque actually being exported?
2. If torque is exported as `MY`, does CalculiX beam deck accept and output it as expected?
3. If torque is exported as a front/rear vertical force couple, does the couple magnitude equal the intended pitching moment?
4. Are signs consistent with the internal convention?
5. Does the torque mode affect twist more than total vertical deflection?

### Outputs

Generate:

```text
output/phase14_dual_beam_calibration/b5_torque_parity_diagnosis.csv
output/phase14_dual_beam_calibration/b5_torque_parity_diagnosis.md
```

### Acceptance

One of these must be true:

1. B5 now includes a torque-sensitive diagnostic and can distinguish the torque modes.
2. B5 remains WARN/report-only with a clear explanation of what is missing from the current CalculiX deck/output.

Do not claim torque ownership is validated from UZ-only metrics.

### Commit

After this task:

```bash
git add -p src/hpa_mdo/structure/calculix_beam_export.py scripts/phase14_calculix_beam_benchmarks.py tests/test_phase14_calculix_beam_benchmarks.py
git commit -m "feat: add CalculiX torque ownership diagnostics"
```

---

## Task F: Improve Main Comparison CSV And Summary

### Files likely to modify

```text
scripts/phase14_calculix_beam_benchmarks.py
```

### Required schema improvements

The main comparison CSV should make benchmark status unambiguous. Add columns as available:

```text
case_id
case_name
status
status_reason
main_tip_uz_internal_m
main_tip_uz_calculix_m
main_tip_error_pct
rear_tip_uz_internal_m
rear_tip_uz_calculix_m
rear_tip_error_pct
max_uz_internal_m
max_uz_calculix_m
max_uz_error_pct
root_reaction_fz_internal_n
root_reaction_fz_calculix_n
wire_reaction_fz_internal_n
wire_reaction_fz_calculix_n
total_reaction_fz_raw_n
total_reaction_fz_corrected_n
reaction_residual_n
twist_proxy_internal_rad
twist_proxy_calculix_rad
twist_proxy_error_pct
engineering_interpretation
```

If some columns are not available for B1/B2/B3, write blank values or `nan` consistently. Do not mix incompatible meanings in the same column.

### Summary rules

`comparison_summary.md` must separate:

```text
PASS = trusted for the metric named in the row
WARN = ran successfully but metric is not yet trusted
FAIL = parity target missed for a metric that should be comparable
SKIP = solver or case not available
```

For B4 and B5, explicitly say which quantities are trusted:

```text
B4: displacement parity may be trusted if within tolerance; reaction truth depends on reaction bookkeeping.
B5: torque parity requires twist/rotation/couple diagnostic; UZ-only is insufficient.
```

### Outputs

Regenerate:

```text
output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv
output/phase14_dual_beam_calibration/comparison_summary.md
```

### Commit

If this is a separate reporting-only change:

```bash
git add -p scripts/phase14_calculix_beam_benchmarks.py
git commit -m "feat: clarify CalculiX beam benchmark comparison reporting"
```

If already naturally included in B2/B4/B5 commits, do not create an artificial extra commit.

---

## Task G: Documentation Update

### Files to modify

```text
docs/calculix_parity_gate.md
```

### Required content

Update the document so future agents cannot overclaim this route.

It must clearly say:

1. B1 validates basic units, E/I, pipe section syntax, load direction, root clamp, and CalculiX execution.
2. B3 supports linear dual-beam no-wire displacement parity.
3. B2 is either fixed or remains a known tapered-section warning with evidence.
4. B4 vertical-wire displacement can be useful, but support reaction truth requires correct reaction bookkeeping.
5. B5 torque ownership must use twist/rotation/couple metrics, not UZ-only.
6. CalculiX is the Mac-local daily cross-check.
7. ANSYS/APDL remains final external check.
8. ASWING is conceptual future reference only.
9. NLGEOM is deferred until linear parity is clean.
10. `WIRE_MAIN_TRUSS` is not the first parity target; APDL-style vertical `UZ=0` is the first wire rung.

### Commit

```bash
git add -p docs/calculix_parity_gate.md
git commit -m "docs: clarify CalculiX parity gate trust policy"
```

---

## Task H: Final Verification

Run:

```bash
./.venv/bin/python -m pytest tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
```

If related hifi parser/runner code changed, also run:

```bash
./.venv/bin/python -m pytest tests/test_hifi_calculix_runner.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
```

Run the full benchmark:

```bash
./.venv/bin/python scripts/phase14_calculix_beam_benchmarks.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration/round3_benchmarks
```

Inspect:

```text
output/phase14_dual_beam_calibration/comparison_summary.md
output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv
output/phase14_dual_beam_calibration/b2_taper_diagnosis.md
output/phase14_dual_beam_calibration/b4_wire_reaction_diagnosis.md
output/phase14_dual_beam_calibration/b5_torque_parity_diagnosis.md
```

Final git check:

```bash
git status --short
git log --oneline -8
```

Working tree should be clean except ignored/generated output artifacts.

---

## Final Response Format

At the end, report in this structure:

```text
Commits:
- <hash> <message>
- <hash> <message>

Verification:
- <command> -> <result>
- <command> -> <result>

Benchmark verdict:
- B1: PASS/WARN/FAIL, short reason
- B2: PASS/WARN/FAIL, short reason
- B3: PASS/WARN/FAIL, short reason
- B4: PASS/WARN/FAIL, short reason
- B5: PASS/WARN/FAIL, short reason

Engineering judgment:
1. Is the CalculiX beam parity gate trustworthy for B1/B3?
2. Is B2 solved or still a tapered-section mismatch?
3. Is B4 wire reaction trustworthy or only kinematic?
4. Is B5 actually measuring torque now?
5. Which result should still go to APDL?

Artifacts:
- output/phase14_dual_beam_calibration/...
```

Do not provide vague claims like "looks good" without numbers.

---

## Stop Conditions

Stop and report instead of forcing a bad patch if:

1. B2 requires changing production internal beam physics and the physical meaning is not obvious.
2. B4 reaction cannot be recovered because CalculiX equation/MPC reaction bookkeeping is not available from current outputs.
3. B5 torque cannot be measured without adding a new solver/output mode that is too large for this round.
4. CalculiX beam rotations require keywords not currently understood and local manuals do not clarify them.
5. A proposed change would affect aerodynamic ranking, hard gates, or production optimization behavior.

In those cases, produce a diagnosis report and leave the benchmark as WARN instead of pretending it passed.

---

## Desired Outcome

The best possible outcome is:

```text
B1: PASS, basic beam deck verified
B2: PASS or well-diagnosed WARN, tapered EI convention understood
B3: PASS, linear dual-beam no-wire parity credible
B4: displacement PASS, reaction PASS only if force equilibrium is proven
B5: torque diagnostic present, WARN only if true torque readback remains unavailable
```

The minimum acceptable outcome is:

```text
Tests portable.
B2/B4/B5 no longer overclaimed.
Each mismatch has a structural diagnosis report.
comparison_summary.md tells future agents exactly what is and is not trustworthy.
```
