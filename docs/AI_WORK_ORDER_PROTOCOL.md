# AI Work Order Protocol

This protocol turns Baseline A from a single-person deep-development flow into a
team release plus AI work-order queue. It applies to Codex threads working in
`/Volumes/Samsung SSD/hpa-mdo`.

## Current Bounded WO-006 Gate

Baseline A data-authority is restored only for bounded WO-006 SU2 aero calibration.
Before any worker starts WO-006, WO-007 QPROP/XROTOR, RFQ procurement, vendor
selection, or release claims, run:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/check_baseline_a_data_authority.py --check-only
```

Current authority:

- `98.5 kg` is design gross mass authority.
- `106.828608 kg` is suspect P1 screening aggregate only.
- `34.332286 m` / `17.166143 m` are current pipeline span evidence.
- `16.5 m` is local/splice screening only, not procurement truth.
- WO-005 is draft/vendor-screening only.
- WO-006 is allowed only as bounded aero calibration, not release truth, not
  RFQ/procurement truth, and not final aircraft sign-off.
- WO-006 must use `98.5 kg` and current pipeline span authority unless explicitly
  studying sensitivity.
- WO-006R1 current GO mesh-native bridge is smoke-ready only:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r1_go_cfd_bridge/`.
  It proves a repeatable coarse mesh/SU2 readability route, not usable CL/CD,
  drag/power calibration, release truth, procurement truth, or aircraft sign-off.
- WO-006R2 CFD recovery campaign isolated the current blocker at current-GO
  surface panel / section-transition topology:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r2_cfd_recovery_campaign/`.
  It reused the old 1M+ BL/HXT route evidence but still produced no usable CFD
  coefficients and no Baseline A reopen evidence.
- WO-006R3 surface-topology repair produced a current-GO high-mesh no-BL SU2
  handoff:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/`.
  Treat it as route/handoff evidence only. It has marker-owned mesh handoff and
  solver readability evidence, but no boundary-layer/y+ evidence, no usable
  CL/CD/CDi, no drag/power calibration, and no Baseline A reopen evidence.
  Later WO-006 work must continue from the BL/core ownership artifacts instead
  of using WO-006R3 coefficients as aerodynamic truth.
- WO-006R4 BL ownership repair is complete:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r4_bl_ownership_repair/`.
  Verdict: `wo006r4_adapter_limitation_proven`. It did not emit
  `bl_mesh_handoff.v1.json`. The Gmsh-owned BL route still fails at DAE31-family
  PLC blockers, and blind BL diagonal swapping remains rejected after
  `Unknown curve -1550`. The mesh-native owned-BL block has positive near-wall
  topology and an estimated first-layer y+ basis, but the current adapter lacks a
  conformal owned-BL + core merge / mixed-element SU2 writer. Treat R4 as the
  next repair target definition, not as BL/y+ CFD evidence or coefficient truth.
- WO-006R5 BL+core merge is complete:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r5_bl_core_merge/`.
  Verdict: `wo006r5_core_merge_limitation_proven`. It did not emit
  `bl_mesh_handoff.v1.json`. The preserved-core probe keeps the core interface
  envelope without remeshing, but core quality still fails and BL/core coupling is
  partial at `wake_cut` / `span_cap`. A direct all-non-wall BL boundary core
  surface is not watertight. Treat R5 as a core-interface / mesh-quality blocker
  proof, not as BL/y+ CFD evidence or coefficient truth.
- WO-006R6 core-interface repair is complete:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/`.
  Verdict: `wo006r6_core_quality_limitation_proven`. It did not emit
  `bl_mesh_handoff.v1.json`. The preserved-core route still keeps the interface
  envelope, but core quality fails on non-positive SICN/SIGE/volume, and the
  wake/span-cap topology is still not a zero-unmatched BL/core handoff. Treat R6
  as a stronger blocker proof: next work must repair preserved-core quality
  without remeshing the interface, then resolve the wake/span-cap topology
  contract before any mixed-element SU2 handoff or coefficient claim.
- WO-006F SU2 engineering-result recovery campaign is complete as a campaign
  package:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/`.
  Verdict: `wo006f_campaign_incomplete`. It ran no-BL NS/RANS/Euler,
  OpenVSP/Gmsh, OpenVSP CFDMesh, and R6 BL/core multizone probes. No final
  physically credible SU2 CL/CD exists. The sign-correct no-BL RANS pair
  (`CL=1.289421542`, `CD=0.5555196327`) is rejected as far too draggy and not
  converged; the multizone probe launches but is only route evidence until core
  quality, wake/span-cap coupling, and force coefficient ownership pass.
- WO-006H reopened CFD campaign is complete as a local-hard-limit plus executable
  HPC case:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_reopened_cfd_campaign/`.
  Verdict: `su2_local_hard_limit_proven_with_executable_hpc_case`. It supersedes
  the earlier H larger-compute-only verdict. Local no-BL HXT control reached
  `3,790,657` cells / `675,820` nodes with marker / quality pass, but no-BL
  remains resource / marker / sign-control evidence only. Finer no-BL probes
  (`h=0.05` HXT and `h=0.04` Delaunay) fail quickly with topology/PLC-style
  errors, not memory exhaustion. BL/core still does not clear the conformal
  interface gate: full BL boundary preserved-core fails with PLC intersection,
  and preserved-interface Alg1 has non-positive volumes plus unmatched BL/core
  faces. Treat WO-006H as local toolchain/topology hard-limit evidence with an
  executable HPC case, not as SU2 aero calibration.

## Baseline A Rule

Baseline A remains a team-release package, not final aircraft sign-off. The
current restored authority gate only permits bounded WO-006 aero calibration;
it does not promote the release package, RFQ/procurement artifacts, or SU2 smoke
outputs into final design truth.

The current generated evidence package is:

- `output/baseline_A_team_release/baseline_A_team_release.md`
- `output/baseline_A_team_release/geometry_freeze.json`
- `output/baseline_A_team_release/mass_budget.csv`
- `output/baseline_A_team_release/cg_summary.json`
- `output/baseline_A_team_release/margin_budget.md`
- `output/baseline_A_team_release/manufacturable_geometry_audit/`
- `output/baseline_A_team_release/carbon_tube_rfq_pack.md`
- `output/baseline_A_team_release/controlled_station_span_splice_manifest.csv`
- `output/baseline_A_team_release/procurement_risk_register.json`
- `output/baseline_A_team_release/team_work_packages.md`

The current structural blocker verdict is
`p1_local_load_path_ready_for_coupon_fem`. That means P1 can proceed to
coupon/local FEM. It does not prove final adhesive, laminate, tube-wall,
buckling, manufacturing, flight-dynamics, or aircraft sign-off.

The old mass / CG / margin ledger verdict `mass_cg_margin_ledger_ready` is historical/generated evidence under data-authority repair, not active current truth.
Its rows are screening estimates unless a row explicitly says otherwise;
`98.5 kg` is the design mass authority, `106.828608 kg` is suspect P1 screening
aggregate, managed CG is the `0.75 m` screening row, and uncompensated CG remains
rejected.

The current manufacturable geometry audit verdict is
`geometry_freeze_needs_fix`. The smooth pathfinder is usable for Baseline A
team-release engineering work, but continuous dimensions, station/span/splice
contracts, and RFQ/shop-facing tube/rib/control stations are not final drawing
control. WO-005 carries those warnings into vendor-screening language instead
of treating them as either final sign-off or immediate Baseline A reopen.

The current carbon tube RFQ pack is `carbon_tube_rfq_pack_draft_vendor_screening`.
It may support internal vendor-question drafting only. It does not authorize tube
purchase, supplier selection, shop drawings, spar-spec changes, procurement
truth, or final aircraft sign-off. Vendor evidence that invalidates tube OD/wall,
splice fit, layup/modulus, mass/CG, 3 m shipping, or y=3 m inboard splice
assumptions must return through change control before any procurement use.

## Worker Startup

Every AI worker must first read:

1. `README.md`
2. `CURRENT_MAINLINE.md`
3. `docs/AI_WORK_ORDER_PROTOCOL.md`
4. `docs/work_orders/QUEUE.md`
5. The specific work-order prompt
6. `output/baseline_A_team_release/` when the task touches Baseline A

If these sources conflict, use this priority:

1. Latest explicit user instruction
2. `CURRENT_MAINLINE.md`
3. `output/baseline_A_team_release/data_authority_table.csv`
4. `docs/reports/baseline_A_data_authority_conflict_register.md`
5. `README.md`
6. Generated outputs such as `geometry_freeze.json`
7. Older reports and task packs

## Work Order Lifecycle

1. Pick the highest-priority unblocked work order.
2. State whether the task is code, docs, analysis, or generated artifact work.
3. Keep the write scope narrow.
4. Run the smallest credible verification first, then broader verification if
   the change affects shared behavior.
5. Update `README.md` and/or `CURRENT_MAINLINE.md` when the task changes the
   formal pipeline, recommended commands, candidate state, engineering trust
   boundary, next priority, or public claim language.
6. Output a reviewer prompt that another Codex thread can use to audit the work.
7. Run `git add -p` for only relevant files and commit one work order per commit.

## Mandatory Review Labels

Every work-order report must choose one of these labels:

- `pass`: evidence supports the work-order claim inside the stated trust boundary.
- `needs_fix`: useful progress, but an implementation or documentation issue
  remains before the work order can close.
- `dangerous_assumption`: the result is likely to mislead future work unless the
  assumption is corrected or quarantined.
- `reopen_risk`: the finding may force Baseline A redesign or user decision.

## Decision Escalation

Ask the user only when the work affects one of these:

- Large external shape or main planform
- Main/rear spar specification
- Weight/CG or rebalance strategy
- Procurement commitment
- Baseline A reopen trigger

Do not ask for routine local choices such as report wording, test slice choice,
or internal helper structure.

## Engineering Honesty Checklist

Before reporting success, check:

- Are units and sign conventions explicit?
- Is load ownership clear?
- Is the result screening, coupon/FEM, or final evidence?
- Did the task accidentally treat QPROP/XROTOR as structural-blocker truth?
- Did it turn the direct spar-pair stress-test warning into aero-surface sign-off?
- Did it hide the C04 original peel fail evidence?
- Did it accept uncompensated CG?
- Did it overclaim from passing tests?

## Verification Minimum

Each worker should run:

```bash
PYTHONPATH=src ./.venv/bin/python -m pytest <relevant tests>
PYTHONPATH=src ./.venv/bin/python -m ruff check <changed python files or dirs>
git diff --check
```

If the task changes generated release artifacts, also rerun:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/build_baseline_a_release.py
```

## Required Report Shape

Each worker final report must include:

- verdict
- changed files
- verification
- engineering caveats
- reviewer prompt
- next recommended work order

Keep the report short enough for a 30-minute daily review.
