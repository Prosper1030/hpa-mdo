# Baseline A Work Order Queue

Queue owner: 代理總工程師 / AI 工作總控.

## Current Bounded WO-006 Gate

Baseline A data-authority is restored for bounded WO-006 aero calibration only.
Do not treat this as release truth, RFQ/procurement truth, or final aircraft
sign-off. Do not start WO-007 QPROP/XROTOR, procurement/RFQ actions, vendor
selection, propeller optimization, or Baseline A release claims from WO-006
without a separate authority review.

Current authority summary:

- `98.5 kg` is the current design gross mass authority.
- `106.828608 kg` is suspect P1 screening aggregate only.
- `34.332286 m` / `17.166143 m` are current pipeline span evidence.
- `16.5 m` is local/splice screening only.
- WO-005 remains draft/vendor-screening only.
- P1/C04 remains coupon/local FEM readiness only.
- WO-006 must use `98.5 kg` and current pipeline span authority unless explicitly
  studying sensitivity.

Current release package:

- `output/baseline_A_team_release/`
- release verdict: `baseline_A_data_authority_restored_wo006_unblocked`
- mass / CG / margin ledger verdict: `mass_cg_authority_bounded_wo006_ready`
- manufacturable geometry audit verdict: `geometry_freeze_needs_fix`
- current structural blocker verdict: `p1_local_load_path_ready_for_coupon_fem`
- Baseline A status: bounded WO-006 SU2 validation may proceed as aero
  calibration only. Remaining mass/span/RFQ conflicts block release,
  procurement, RFQ truth, shop drawings, and final aircraft sign-off.
  Coupon/local FEM planning may continue inside screening boundaries, and WO-005
  remains draft-only.

## Queue Rules

- Pick the first unblocked work order unless a newer user instruction overrides it.
- Do not bundle independent work orders into one commit.
- Every work order must report: verdict, changed files, verification, engineering
  caveats, reviewer prompt, and next recommended work order.
- Do not promote screening evidence into final aircraft sign-off.
- Do not let background lanes reopen Baseline A unless a reopen trigger is met.
- Do not stage unrelated dirty `output/phase12...` or deleted `output/phase14...`
  files.
- Ask the user only when a finding affects large external shape, procurement,
  weight/CG, main/rear spar specification, or Baseline A reopen.

## Reopen Triggers

Baseline A should only reopen when one of these is supported by evidence:

- Power improvement over Baseline A is greater than roughly 5-8%.
- Weight improvement over Baseline A is greater than roughly 2-3 kg.
- Baseline A has an unrecoverable trim, CG, torsion, structural, or mission fail.
- Vendor/RFQ evidence invalidates the current spar/tube/splice assumptions.
- Qualified aero-surface mapping invalidates the current direct stress-test warning read.
- Tail/control authority cannot be closed inside the managed CG basis.

## Priority Queue

| ID | Priority | Status | Work order | Owner lane | Why now |
|---|---:|---|---|---|---|
| WO-001 | P0 | done | Baseline A release builder + work-order protocol | release tooling | Completed in `5bc130a8`; do not mix backlog features into this work order |
| WO-002 | P0 | done | Mass / CG / Margin Budget Ledger | chief engineering | Ledger lives in `output/baseline_A_team_release/`; do not promote estimate rows to measured/frozen |
| WO-003 | P0 | done | Design-Space Freeze Audit | chief engineering + aero/geometry | Completed in `output/baseline_A_team_release/design_space_freeze_audit/`; verdict `baseline_A_freeze_reasonable` |
| WO-004 | P0 | done | Manufacturable Smoothness / Discretization Audit | manufacturing + geometry | Completed in `output/baseline_A_team_release/manufacturable_geometry_audit/`; verdict `geometry_freeze_needs_fix` |
| WO-005 | P0 | done | Carbon Tube RFQ + Procurement Pack | manufacturing + structures | Completed in `output/baseline_A_team_release/`; old `carbon_tube_rfq_pack_ready` is historical/generated evidence under data-authority repair, not active current truth; draft/vendor-screening only |
| WO-006 | P1 | queued_bounded | Main-Wing SU2 Baseline Validation | aero validation | May proceed after data-authority restoration only as bounded aero calibration using 98.5 kg and current pipeline span authority; not release/RFQ/procurement/final truth |
| WO-007 | P1 | queued | QPROP / XROTOR Propulsion Interface | propulsion | Give drivetrain a design box while keeping propulsion independent from C04/rib blockers |
| WO-008 | P1 | queued | Competition Turn / Stall / Power Gate | mission + aero + controls | 180 deg turns every ~10 km can drive power/stall/control margins |
| WO-009 | P1 | queued | Control Derivative Matrix | controls | Give control team a sign-convention-safe simulation reference |
| WO-010 | P1 | queued | Tail Motor Authority System | controls + tail hardware | All-moving H/V tail only matters if actuators can move it in wind |
| WO-011 | P1 | queued | Tailboom / Vertical Strut First-Order Model | structures + controls | Tail/wing/pilot connection can move CG, drag, stiffness, and alignment |
| WO-012 | P2 | background | Airfoil Database CST/NSGA Background Lane | airfoil research | Useful long run, but must not block Baseline A release |
| WO-013 | P2 | background | Report / CAD / VSP / STEP Export Automation | release + geometry tooling | Important reusable asset after release semantics and geometry audits settle |
| WO-014 | P3 | later | Random Disturbance / Lake Biwa Wind Simulation | controls + mission robustness | Later robustness lane; queue only for now |

## Work Order Details

### WO-001: Baseline A release builder + work-order protocol

Status: done in commit `5bc130a8`.

Purpose: create `scripts/build_baseline_a_release.py`,
`output/baseline_A_team_release/`, `docs/AI_WORK_ORDER_PROTOCOL.md`,
`docs/work_orders/QUEUE.md`, and the work-order template.

Do not reopen this work order to implement new physics. Future report/export
automation belongs in WO-013.

### WO-002: Mass / CG / Margin Budget Ledger

Status: done. The repeatable ledger is generated by
`scripts/build_baseline_a_release.py` into `output/baseline_A_team_release/`.

Purpose: establish the central mass, CG, drag/power, and structural margin truth
surface for Baseline A so the user no longer hand-calculates weight and balance.

Allowed scope:

- Add a ledger builder and a small data schema for component name, mass, x/y/z
  location, owner, source, confidence level (`estimate`, `quoted`, `measured`,
  `frozen`), and flags for CG / drag / power / structure effects.
- Consume current Baseline A release artifacts and P1 closure data as seed rows.
- Output `mass_budget.csv`, `cg_summary.json`, `margin_budget.md`, and a readable
  markdown table or chart.

Disallowed scope:

- Do not change geometry, spar specs, C04 design, or tail design.
- Do not turn estimate-level numbers into measured/frozen values.

Required verdict: `mass_cg_margin_ledger_ready` or
`mass_cg_margin_ledger_incomplete`.

### WO-003: Design-Space Freeze Audit

Status: done. Artifacts live in
`output/baseline_A_team_release/design_space_freeze_audit/`.

Purpose: check whether Baseline A is a reasonable freeze candidate, not merely
the first pathfinder that connected downstream.

Allowed scope:

- Revisit mission / geometry design-space evidence with fast models only.
- Apply manufacturable grid assumptions such as 0.1 m or 0.05 m span grid and
  reasonable chord / rib / spar segment discretization.
- Compare a small top-candidate set against Baseline A.
- Output `design_space_freeze_audit.md`, `candidate_compare_table.csv`, and
  `baseline_A_reopen_risk.json`.

Disallowed scope:

- Do not run heavy FEM or full SU2 for every candidate.
- Do not reopen Baseline A unless the reopen trigger evidence is explicit.

Required verdict: `baseline_A_freeze_reasonable`,
`baseline_A_freeze_needs_fix`, or `baseline_A_reopen_risk`.

Completion read: `baseline_A_freeze_reasonable`. No nearby manufacturable
candidate exceeded the power / weight / trim / CG / torsion / mission /
manufacturing reopen triggers. The best nearby fast-model row showed about
`4.63%` crank-power improvement, below the 5-8% trigger and without a downstream
geometry / CG / torsion / splice / P1 load-path chain. Release mass + tail CD0
charge remains a power-budget watch item, not final mission sign-off.

### WO-004: Manufacturable Smoothness / Discretization Audit

Status: done. Artifacts live in
`output/baseline_A_team_release/manufacturable_geometry_audit/`.

Purpose: verify that the smooth production geometry is actually buildable and
not hiding discontinuities or non-manufacturable continuous dimensions.

Allowed scope:

- Check main-wing section transitions, chord, twist, dihedral, loaded shape,
  rib spacing, 3 m segment boundaries, and spar splice placement.
- Classify each issue as `smooth_and_manufacturable`,
  `smooth_but_not_manufacturable`, `manufacturable_but_geometry_discontinuity_risk`,
  or `needs_redesign`.
- Output `manufacturable_geometry_audit.md`,
  `geometry_discretization_report.csv`, and `smoothness_warning.json`.

Disallowed scope:

- Do not redesign the external shape inside the audit.
- Do not produce production drawings or STEP automation here.

Required verdict: `geometry_freeze_manufacturable`,
`geometry_freeze_needs_fix`, or `geometry_freeze_reopen_risk`.

Completion read: `geometry_freeze_needs_fix`. The smooth Baseline A pathfinder
is acceptable for team-release engineering work and did not show a large
external-shape discontinuity or explicit Baseline A reopen trigger. It is not
ready to hand to shop as controlled dimensions. WO-005 resolves the next RFQ
screening language layer by carrying continuous dimension rounding,
airfoil/control/transition station contracts, the 0.30 m release rib basis
versus the selected 0.345 m stiffness label, 3 m splice locations versus
materialized spar-joint rib stations, structural `16.5 m` half-span versus
aero/rib station extent, and the inboard splice zero-margin warning into a
vendor question pack.

### WO-005: Carbon Tube RFQ + Procurement Pack

Status: done. Artifacts live in `output/baseline_A_team_release/`.

Purpose: turn the screening carbon-tube and splice assumptions into a vendor/RFQ
package without committing to procurement beyond evidence.

Allowed scope:

- Expand `output/baseline_A_team_release/carbon_tube_rfq_spec.md` into a
  procurement-ready screening pack.
- Include OD/ID, wall, tolerance, ovality, straightness, layup, QA coupon, 3 m
  segment shipping, splice-fit, ferrule/spigot, and surface-prep questions.
- Include a controlled station/span/splice manifest that resolves or explicitly
  carries WO-004 warnings before asking vendors to interpret dimensions.
- Flag any vendor answer that would trigger mass/CG, spar-spec, or Baseline A
  reopen review.

Disallowed scope:

- Do not place orders or choose a supplier as final.
- Do not change spar dimensions without user decision.

Required verdict: `carbon_tube_rfq_pack_ready` or
`carbon_tube_rfq_pack_incomplete`.

Current read: `carbon_tube_rfq_pack_draft_vendor_screening`. The pack may be used
only as an internal vendor-question draft. The `16.5 m` half-span and 3 m splice
stations are local/splice screening references, not procurement truth. It does
not place orders, choose a supplier, release shop drawings, or sign off the
aircraft.

### WO-006: Main-Wing SU2 Baseline Validation

Status: queued_bounded after Baseline A data authority restoration for bounded
aero calibration.

Purpose: calibrate current Baseline A aerodynamic models against a bounded SU2
baseline, similar in spirit to using CCX to calibrate structural fast models.

Allowed scope:

- Run Baseline A main wing first, optionally one or two nearby geometries.
- Compare CL, CD, CDi, profile drag, and mission-model deltas against AVL /
  Fourier / XFOIL / proxy values.
- Output SU2 comparison artifacts and a Baseline A reopen-risk read.
- Use `98.5 kg` and current pipeline span authority unless the run is explicitly
  labeled as sensitivity.

Disallowed scope:

- Do not run full design-space CFD.
- Do not call SU2 final truth or use it to pass structural blockers.
- Do not use SU2 output as release truth, RFQ/procurement truth, or final
  aircraft sign-off.

Required verdict: `su2_baseline_calibration_usable`,
`su2_baseline_needs_fix`, or `su2_baseline_reopen_risk`.

### WO-007: QPROP / XROTOR Propulsion Interface

Purpose: give the drivetrain/propulsion team a clear design box while preserving
QPROP/XROTOR as an independent propulsion lane.

Allowed scope:

- Code current propeller assumptions into a repeatable interface.
- Output thrust required, cruise power range, RPM range, diameter range, shaft
  torque, prop efficiency estimate, and approximate mass/radial distribution if
  available.

Disallowed scope:

- Do not produce final blade manufacturing design.
- Do not mix propulsion results into rib/C04 structural blocker verdicts.

Required verdict: `propulsion_interface_ready` or
`propulsion_interface_incomplete`.

### WO-008: Competition Turn / Stall / Power Gate

Purpose: add the first competition maneuver gate for roughly 180 deg turns every
10 km without jumping to full dynamic simulation.

Allowed scope:

- Build a low-order turn model using turn radius or bank angle, speed, mass,
  wing loading, and CLmax margin.
- Output extra turn power, stall margin, tail/control demand, and pass/warning
  status.

Disallowed scope:

- Do not build full random disturbance or full 6-DOF simulation.

Required verdict: `turn_stall_power_gate_ready`,
`turn_stall_power_gate_needs_fix`, or `turn_stall_power_reopen_risk`.

### WO-009: Control Derivative Matrix

Purpose: give the control team a low-order, unit-safe derivative matrix for PID
and simulation familiarization.

Allowed scope:

- Generate longitudinal, lateral/directional, H-tail, and V-tail control
  derivatives from current Baseline A artifacts.
- Define reference coordinate system, sign convention, units, and intended use.
- Output `control_derivative_matrix.csv`, `control_interface_pack.md`, and usage
  notes.

Disallowed scope:

- Do not call it final flight-dynamics sign-off.

Required verdict: `control_derivative_matrix_ready` or
`control_derivative_matrix_incomplete`.

### WO-010: Tail Motor Authority System

Purpose: check whether all-moving H-tail/V-tail actuators can actually move the
surfaces under wind/load conditions.

Allowed scope:

- Use a user-configurable max wind speed, default `5 m/s`.
- Estimate required hinge/pivot torque, motor torque margin, deflection reserve,
  and tail load.
- Output motor authority report and candidate actuator requirements.

Disallowed scope:

- Do not freeze actuator procurement without user decision.
- Do not ignore a negative motor margin; it may affect tail design/control layout.

Required verdict: `tail_motor_authority_screen_ready`,
`tail_motor_authority_needs_fix`, or `tail_motor_authority_reopen_risk`.

### WO-011: Tailboom / Vertical Strut First-Order Model

Purpose: model the first-order geometry, mass, stiffness, and drag of the
tailboom / longitudinal tube / vertical strut connection before detail FEM.

Allowed scope:

- Include max 3 m segment constraints.
- Estimate effects on CG, tail stiffness, drag, wing/tail relative alignment,
  and structural load path.
- Output `tailboom_strut_first_order_model.md`,
  `tailboom_mass_drag_estimate.csv`, and `reopen_risk.json`.

Disallowed scope:

- Do not start detail FEM in this work order.

Required verdict: `tailboom_strut_model_ready`,
`tailboom_strut_model_incomplete`, or `tailboom_strut_reopen_risk`.

### WO-012: Airfoil Database CST/NSGA Background Lane

Purpose: run longer airfoil discovery without blocking Baseline A.

Allowed scope:

- Symmetric airfoils: tail candidates via discrete/CST search before NSGA if
  useful.
- Non-symmetric airfoils: main wing / propeller CST + NSGA background search.
- Promote only candidates with complete polar sweeps into the database.
- Store geometry coefficients, polar grid, Re range, alpha range, clean/rough
  status if available, source/generation method, and trust level.

Disallowed scope:

- Do not block Baseline A release.
- Do not reopen Baseline A unless power / stall / trim improvement is large and
  verified against full polar evidence.

Required verdict: `airfoil_background_lane_running`,
`airfoil_database_candidate_ready`, or `airfoil_lane_incomplete`.

### WO-013: Report / CAD / VSP / STEP Export Automation

Purpose: automate human-readable and engineering-usable geometry/report exports
after the release semantics and geometry audits are stable.

Allowed scope:

- Minimum version: tables + VSP + markdown preview.
- Later extensions: STEP if feasible, station tables, tube geometry, loaded /
  jig / ground-shape visualization, truss/support preview.

Disallowed scope:

- Do not let export automation block Baseline A validation.
- Do not claim production drawing release unless change control says so.

Required verdict: `export_automation_minimum_ready`,
`export_automation_incomplete`, or `export_lane_blocked`.

### WO-014: Random Disturbance / Lake Biwa Wind Simulation

Purpose: later control/mission robustness lane for wind, gust, route, and
disturbance response.

Allowed scope:

- Queue only for now.
- A future minimum version may define route input and a simple disturbance
  framework.

Disallowed scope:

- Do not prioritize ahead of Baseline A release, ledger, freeze audit, geometry
  audit, RFQ, propulsion/control interfaces, or tail first-order models.

Required verdict: `disturbance_lane_queued` unless explicitly promoted later.

## Next Recommended Work Order

WO-006 SU2 is now the next recommended task after data-authority restoration, but only as bounded aero
calibration. The checker, authority table, and conflict register show current
channel wording is clean; remaining mass/span/RFQ conflicts block release and
procurement, not this bounded validation lane.

```text
/goal In /Volumes/Samsung SSD/hpa-mdo, execute WO-006 after data-authority restoration as bounded aero calibration only.

Role:
代理總工程師 / AI work-order executor. Keep Baseline A engineering-honest and do
not overclaim screening evidence. WO-006 SU2 is allowed only as bounded aero
calibration, not release truth, RFQ/procurement truth, or final aircraft sign-off.

Read first:
- README.md
- CURRENT_MAINLINE.md
- docs/AI_WORK_ORDER_PROTOCOL.md
- docs/work_orders/QUEUE.md
- output/baseline_A_team_release/
- output/baseline_A_team_release/carbon_tube_rfq_pack.md

Task:
Run bounded main-wing SU2 validation for the current Baseline A pathfinder.
Use `98.5 kg` and current pipeline span authority unless explicitly running a
labeled sensitivity. Compare CL, CD, CDi, profile drag, and model deltas against
AVL/Fourier/XFOIL/proxy evidence. Output a calibration read and reopen-risk
read, but do not promote SU2 to release, procurement, RFQ, structural, or final
aircraft truth.

Boundary:
Do not run QPROP/XROTOR, full design-space CFD, propeller optimization, NSGA,
random disturbance simulation, procurement, vendor selection, or final CAD
automation. Do not turn SU2 or checker pass/fail into aircraft sign-off. Ask
the user only if the evidence affects large external shape, spar spec, mass/CG,
procurement commitment, or Baseline A reopen.

Required output:
- verdict: su2_baseline_calibration_usable / su2_baseline_needs_fix / su2_baseline_reopen_risk
- changed files
- exact mass/span authority basis used
- verification
- engineering caveats
- whether SU2 changes any Baseline A reopen risk
- reviewer prompt
- next recommended work order

Verification:
- run targeted SU2/calibration tests or smoke checks available in repo
- run scripts/check_baseline_a_data_authority.py --check-only
- run ruff on changed Python files
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
7. Did it keep background lanes from casually overturning Baseline A?

Return pass / needs_fix / dangerous_assumption / reopen_risk with line-level
evidence.
```
