# Phase 14 CalculiX B2/B5 Solution-Hunt Goal

這份 prompt 是給 Goal mode / long-running Codex worker 使用的自包含任務書。
預期 worker 可以使用 GPT-5.5、xhigh effort，連續工作 2 到 4 小時。

這一輪不是再產一份診斷報告而已。這一輪的目標是：針對 Round 3 剩下的兩個核心缺口，找出可執行的解法路線，能解就實作，不能解就給出工程上可接受的 truth-route / fallback policy。

Round 3 結論：

- B1：PASS，單梁 constant-section 基本 CalculiX beam deck 可用。
- B3：PASS，dual-beam no-wire displacement parity 可用。
- B4：PASS for APDL-style vertical `UZ=0` wire surrogate，修正後 root/wire reaction bookkeeping 可用。
- B2：WARN，tapered single tube 仍有 10-12% stable gap。
- B5：WARN，torque ownership 還不能用 UZ-only / translational outputs 驗證。

本輪專注 B2 和 B5。

---

## Short Prompt To Paste Into Goal Mode

請讀並執行：

`docs/codex_prompts/phase14_calculix_b2_b5_solution_hunt_goal.md`

這是一個 2 到 4 小時的結構驗證 solution-hunt 任務。請不要只重跑 Round 3；你要針對 B2 tapered tube 10-12% gap 和 B5 torque ownership 找解法。優先使用本地 CalculiX manual、現有 CalculiX runner/exporter、APDL exporter/ANSYS decks、以及小型 controlled benchmarks。能把 gap 收斂就實作；不能收斂就輸出可接受的 engineering truth route。不要改 aerodynamic ranking、hard gates、dual_beam_production production physics，也不要加入 arbitrary calibration factor。完成後照 AGENTS.md 分任務 commit，最後回報測試、benchmark、工程判讀、下一個 APDL/ANSYS target 和 commit hash。

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

Current useful files:

```text
src/hpa_mdo/structure/calculix_beam_export.py
scripts/phase14_calculix_beam_benchmarks.py
tests/test_phase14_calculix_beam_export.py
tests/test_phase14_calculix_beam_benchmarks.py
docs/calculix_parity_gate.md
docs/Manual/ccx_2.22.pdf
output/phase14_dual_beam_calibration/b2_taper_diagnosis.md
output/phase14_dual_beam_calibration/b4_wire_reaction_diagnosis.md
output/phase14_dual_beam_calibration/b5_torque_parity_diagnosis.md
```

Solver discovery should use:

```text
load_config("configs/blackcat_004.yaml") + find_ccx(cfg)
```

Do not assume `which ccx` is enough.

---

## Hard Constraints

Do not do these things:

1. Do not change aerodynamic ranking.
2. Do not change hard gates.
3. Do not run broad aero optimization.
4. Do not silently change `dual_beam_production` production physics.
5. Do not tune internal EI/GJ just to match CalculiX.
6. Do not add arbitrary calibration/fudge factors.
7. Do not enable NLGEOM as a shortcut.
8. Do not implement ASWING-like behavior.
9. Do not claim B2 or B5 passed unless the measured quantity actually supports that claim.
10. Do not force-add ignored `output/` artifacts unless explicitly requested.

Allowed changes:

1. Add small, controlled CalculiX decks for B2/B5 truth probes.
2. Add APDL deck export for B2/B5 if existing APDL exporter can be reused or extended cleanly.
3. Add section-force output to CalculiX beam decks if justified.
4. Add parsers for CalculiX `.dat` / `.frd` section-force or rotation-related output.
5. Add scripts/reports under Phase 14 naming.
6. Add tests for parsers and benchmark bookkeeping.
7. Update docs/trust policy.

---

## Engineering Mindset

Act as a structural engineer first and a coding engineer second.

For B2, the question is:

```text
Why does a tapered tube become about 10-12% stiffer in CalculiX B32R + PIPE than in the internal / Euler-Bernoulli reference, while constant-section cases match?
```

For B5, the question is:

```text
How do we verify torque ownership with an observable that actually measures torque/twist/moment, not just vertical tip displacement?
```

You are looking for a solution route. A valid solution can be:

1. A code fix that makes CalculiX parity physically correct.
2. A new CalculiX output/parse route that measures the missing quantity.
3. An APDL-ready truth deck when CalculiX cannot answer the question cleanly.
4. A documented trust policy that says this quantity must remain external-FEM checked.

Do not pretend every problem must be solvable inside the current B32R + PIPE route.

---

## Start-Up Reproduction

Run first:

```bash
git status --short
git log --oneline -10
./.venv/bin/python -m pytest tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
./.venv/bin/python scripts/phase14_calculix_beam_benchmarks.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration/round4_baseline
```

Read:

```text
output/phase14_dual_beam_calibration/b2_taper_diagnosis.md
output/phase14_dual_beam_calibration/b5_torque_parity_diagnosis.md
docs/calculix_parity_gate.md
```

Confirm baseline:

```text
B2 baseline internal-vs-CCX gap about 10.7%
B2 mesh/sampling sweep gap remains roughly 10-12%
B5 main_beam_my_about_main_spar indistinguishable from control by current twist proxy
B5 front_rear_vertical_couple observable but twist mismatch about 93%
```

---

## Local CalculiX Manual Facts To Verify

Use local manual first:

```bash
pdftotext docs/Manual/ccx_2.22.pdf - | rg -n -C 4 "\\*BEAM SECTION|GENERAL|NODAL THICKNESS|SECTION FORCES|\\*EL FILE|\\*NODE FILE|\\*NODE PRINT|B32R|PIPE"
```

Important facts that must be checked and cited in the local report:

1. `*BEAM SECTION, SECTION=PIPE` is defined by outer radius and thickness.
2. CalculiX internally expands PIPE/BOX beam sections into an equivalent rectangular expanded beam visualization; this may matter for tapered interpretation.
3. `SECTION=GENERAL` is not a normal B32R solution path; the manual says GENERAL can only be used for user element type U1.
4. `*NODAL THICKNESS` can define variable beam thicknesses, but it defines local thicknesses in 1/2 directions; you must test whether this is relevant to a pipe/tube route before trusting it.
5. `*NODE FILE U` stores displacements; beam rotations are not obviously available through the current parser.
6. `*NODE FILE` / `*NODE PRINT RF` external forces include reactions plus applied loads at the node; this explains B4 corrected bookkeeping.
7. `*EL FILE, SECTION FORCES` is beam-relevant and can expose section force meanings:

   ```text
   xx = shear force in local 1
   yy = shear force in local 2
   zz = normal force
   xy = torque
   xz = bending moment about local 2
   yz = bending moment about local 1
   ```

Output:

```text
output/phase14_dual_beam_calibration/ccx_manual_capability_audit.md
```

This report should be short but precise: what CCX can and cannot expose for B2/B5.

---

## Task A: B2 Solution-Hunt

### Current problem

Round 3 showed:

```text
constant-section control: about 0.5-0.6% error
tapered B2: about 10.7% error
sampling sweep: still about 10.6%
mesh sweep: still about 10-12%
```

This points away from simple load/root/sampling bugs.

### Goal

Find whether B2 can be made into a reliable Mac-local CalculiX gate, or whether B2 must be routed to APDL / alternate high-fidelity truth.

### Required probes

#### Probe A1: Manual-backed deck capability audit

Before coding, decide which CalculiX B2 alternatives are even legal:

1. Can `SECTION=GENERAL` be used with B32R? If manual says no, do not implement it.
2. Can `NODAL THICKNESS` help a tapered pipe? If unclear, make a controlled probe; do not assume.
3. Can PIPE taper be represented by one element set with nodal thickness, or only by per-element constant sections?
4. Is the current per-element-section deck a stepwise taper rather than a true linearly tapered beam?

#### Probe A2: NODAL THICKNESS / variable-thickness probe

If feasible, create a small B2 alternative deck:

```text
output/phase14_dual_beam_calibration/round4_b2_solution_hunt/
```

Compare:

1. current B32R + PIPE per-element section
2. B32R + RECT equivalent section with nodal thickness, if physically meaningful
3. B32R + PIPE plus NODAL THICKNESS only if manual/deck behavior shows it is valid

Do not present equivalent RECT as a true pipe unless you can preserve the relevant bending stiffness and explain what torsion/stress quantities become invalid.

#### Probe A3: APDL truth deck for B2

Search existing repo for APDL exporters:

```bash
rg -n "APDL|BEAM188|SECTYPE|CTUBE|ANSYS|ansys" src scripts docs tests
```

If a reusable APDL exporter exists, add a B2 tapered single-tube APDL deck export.

If no clean exporter exists, write a minimal B2 APDL `.inp` / `.mac` deck under:

```text
output/phase14_dual_beam_calibration/apdl_truth_decks/b2_tapered_tube.apdl
```

The deck should include:

```text
BEAM188 or current repo beam element convention
CTUBE/pipe section properties
same y nodes
same taper definition as clearly as APDL supports
same E/G/material
same root clamp
same nodal loads
expected internal/reference tip deflection
expected CalculiX B32R+PIPE tip deflection
```

If ANSYS is not runnable on this Mac, that is fine. The output should be APDL-ready for Windows final check.

#### Probe A4: Optional controlled 3D/shell truth route

Only if it stays small and Mac-safe:

Create a minimal tapered tube high-fidelity CalculiX probe using Gmsh or explicit generated nodes/elements.

Requirements:

```text
small enough to run quickly
same E/nu
root clamp
same total uniform load mapped cleanly
report tip deflection
do not make this production geometry
```

This is optional. Do not let it consume the whole task if APDL deck route is more valuable.

### B2 acceptance

One of these outcomes is acceptable:

1. You find and implement a physically valid Mac-local CalculiX deck variant that brings B2 below 2% vs independent Euler-Bernoulli / internal reference.
2. You show APDL-ready B2 truth deck and document that B2 cannot be trusted with current B32R + PIPE taper.
3. You show evidence that internal/reference is the likely wrong side, but do not change production physics without a separate review.

Output:

```text
output/phase14_dual_beam_calibration/b2_solution_hunt.md
output/phase14_dual_beam_calibration/b2_solution_hunt.csv
output/phase14_dual_beam_calibration/apdl_truth_decks/b2_tapered_tube.apdl
```

Commit after Task A:

```bash
git add -p src/hpa_mdo/structure/calculix_beam_export.py scripts/phase14_calculix_beam_benchmarks.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py docs/calculix_parity_gate.md
git commit -m "feat: add B2 tapered beam solution-hunt route"
```

Use exact staged files only. Do not force-add ignored output unless explicitly necessary.

---

## Task B: B5 Torque Ownership Solution-Hunt

### Current problem

Round 3 showed:

```text
main_beam_my_about_main_spar carries 40 N m but looks identical to cm_off_control in centerline twist proxy
front_rear_vertical_couple carries 40 N m and is observable
front_rear_vertical_couple twist mismatch remains about 93%
```

This means B5 is not yet a torque validation gate.

### Goal

Find an observable that can verify torque ownership:

1. beam-axis MY torsion route, or
2. front/rear force-couple torque route, or
3. APDL-ready truth deck if CalculiX cannot expose the needed quantity cleanly.

### Required probes

#### Probe B1: Single-beam torsion sanity case

Create a simple torsion benchmark:

```text
single circular tube
root fixed
tip torque about beam axis
no vertical load
```

Closed-form reference:

```text
theta_tip = T L / (G J)
```

Where:

```text
G = E / (2 * (1 + nu))
J = tube polar second moment
```

Try to recover twist from CalculiX using these options:

1. `*NODE PRINT` or `.dat` displacement/rotation if rotations are available.
2. `*NODE FILE, OUTPUT=2D` if rotations appear in `.frd` or parser can be extended.
3. `*NODE FILE, OUTPUT=3D` expanded beam cross-section geometry; derive twist from rotated cross-section nodes if node mapping is manageable.
4. `*EL FILE, SECTION FORCES` and parse section torque `xy`.

Do not assume rotations are available. Prove it from output.

Output:

```text
output/phase14_dual_beam_calibration/b5_single_beam_torsion_probe.md
output/phase14_dual_beam_calibration/b5_single_beam_torsion_probe.csv
```

#### Probe B2: Add section-force output for beam torque

Based on the CCX manual, try a controlled deck addition:

```text
*EL FILE, SECTION FORCES
S,NOE
```

or the exact syntax that works with ccx 2.23.

Then parse the resulting `.frd` enough to answer:

```text
Does the beam element show the applied torque?
Does main_beam_my_about_main_spar produce nonzero section torque?
Does cm_off_control stay near zero incremental torque?
Does front_rear_vertical_couple produce equivalent moment through shear/bending/couple?
```

If parsing full FRD section-force blocks is too large, write a minimal parser for the known local output block and test it with a fixture.

#### Probe B3: Incremental twist comparison

Raw twist proxy contains baseline link/wire deformation. Compare incremental torque response instead:

```text
delta_twist(mode) = twist_proxy(mode) - twist_proxy(cm_off_control)
```

Report:

```text
internal_delta_twist_rad
calculix_delta_twist_rad
delta_twist_error_pct
absolute_delta_twist_deg
```

This matters because the raw twist is tiny. A 90% relative error may correspond to about 0.04-0.09 degrees, but it still cannot pass torque ownership unless the physics and sign are correct.

#### Probe B4: APDL truth deck for B5

Create APDL-ready decks:

```text
output/phase14_dual_beam_calibration/apdl_truth_decks/b5_main_beam_my_about_main_spar.apdl
output/phase14_dual_beam_calibration/apdl_truth_decks/b5_front_rear_vertical_couple.apdl
output/phase14_dual_beam_calibration/apdl_truth_decks/b5_cm_off_control.apdl
```

Each deck should include:

```text
same dual-beam nodes
same pipe sections
same rigid links / equal DOF constraints as APDL can express
same APDL-style vertical wire UZ=0 surrogate
same vertical loads
same torque / force-couple loads
requested outputs for tip UZ, rotations, root reactions, wire reactions, section moments if available
expected internal and CalculiX values for comparison
```

If existing APDL exporter already supports part of this, reuse it. Do not create a parallel APDL style if one established convention exists.

### B5 acceptance

One of these outcomes is acceptable:

1. You find a CalculiX section-force / rotation route that can validate MY torque ownership.
2. You prove current CalculiX output cannot validate MY, but front/rear force-couple can be used as a reportable torque surrogate with incremental twist metrics.
3. You produce APDL-ready B5 decks and update trust policy: B5 remains external-FEM required.

Output:

```text
output/phase14_dual_beam_calibration/b5_solution_hunt.md
output/phase14_dual_beam_calibration/b5_solution_hunt.csv
output/phase14_dual_beam_calibration/apdl_truth_decks/b5_main_beam_my_about_main_spar.apdl
output/phase14_dual_beam_calibration/apdl_truth_decks/b5_front_rear_vertical_couple.apdl
output/phase14_dual_beam_calibration/apdl_truth_decks/b5_cm_off_control.apdl
```

Commit after Task B:

```bash
git add -p src/hpa_mdo/structure/calculix_beam_export.py scripts/phase14_calculix_beam_benchmarks.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py docs/calculix_parity_gate.md
git commit -m "feat: add B5 torque ownership solution-hunt route"
```

---

## Task C: Decide The Engineering Trust Policy

After Tasks A/B, update:

```text
docs/calculix_parity_gate.md
```

And create/update:

```text
output/phase14_dual_beam_calibration/round4_solution_hunt_summary.md
```

The summary must answer:

1. Is B2 solvable inside Mac-local CalculiX beam parity?
2. If yes, which deck mode is the new B2 truth route?
3. If no, exactly what APDL/ANSYS check is needed?
4. Is B5 MY torque ownership observable in CalculiX?
5. If yes, which output channel proves it?
6. If no, should production torque parity use front/rear force-couple or remain APDL-only?
7. Which quantities are now safe for daily gate?
8. Which quantities still require external FEM?

Do not hide uncertainty. Use wording like:

```text
trusted daily gate
diagnostic only
APDL-required
not yet observable
```

Commit after Task C:

```bash
git add -p docs/calculix_parity_gate.md
git commit -m "docs: update Phase 14 CalculiX solution-hunt trust policy"
```

---

## Required Tests

Run at minimum:

```bash
./.venv/bin/python -m pytest tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
```

If parser or hifi runner code changed:

```bash
./.venv/bin/python -m pytest tests/test_hifi_calculix_runner.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
```

Run the benchmark:

```bash
./.venv/bin/python scripts/phase14_calculix_beam_benchmarks.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration/round4_benchmarks
```

If new solution-hunt script is added, run it and record the exact command.

---

## Final Response Required

Final response must include:

```text
Commits:
- <hash> <message>

Verification:
- <command> -> <result>

B2 solution status:
- solved in CalculiX / APDL-required / still unknown
- key numbers
- engineering reason

B5 solution status:
- MY observable / force-couple only / APDL-required
- key numbers
- engineering reason

Trust policy:
- Daily gate:
- Diagnostic only:
- External FEM required:

Artifacts:
- output/phase14_dual_beam_calibration/...
```

Do not say "looks good" without numbers.

---

## Stop Conditions

Stop and report if:

1. The only way to make B2 pass is to tune EI/GJ without external truth.
2. The only way to make B5 pass is to compare UZ-only metrics again.
3. CalculiX cannot expose rotations/section forces with reasonable effort.
4. APDL exporter work would require a broad rewrite.
5. Any change would affect production aerodynamic ranking or hard gates.

In those cases, produce APDL-ready decks and a clear trust policy instead of forcing a fake pass.

---

## Desired Outcome

Best outcome:

```text
B2 has either a corrected Mac-local CalculiX deck mode or a clear APDL truth deck.
B5 has either a section-force/rotation observable or a clear APDL truth deck.
B1/B3/B4 remain stable.
No production physics is changed without external evidence.
```

Minimum acceptable outcome:

```text
B2 and B5 are no longer open-ended mysteries.
The next external ANSYS/APDL check is fully specified and deck-ready.
The repo docs clearly say what is daily-gate trusted and what is not.
```
