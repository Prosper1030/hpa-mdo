# Baseline A Work Order Queue

Queue owner: 代理總工程師 / AI 工作總控.

## Current Bounded WO-006 Gate

**2026-08-02 highest-priority ready work order:**
`WO-006_OPENFOAM_TRANSITION_BASELINE_RECOVERY.md`. Run it serially on the
accepted Fine full-wing OpenFOAM mesh using the qualified resumable runner.
Success means one stable SST/LM same-mesh engineering diagnostic with a
100-row force/CmPitch window and complete transition/yPlus/force evidence. The
historical SU2 custom mixed-handoff route is not the active local execution
route. Do not start another mesh ladder, physical-time Fine URANS, or design
power work first.

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
- Current OpenFOAM grid-independence work must start from
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_grid_independence_verification/`
  and the recent successful full-wing mirror route (`fe73939a`), with the failed
  same-route grid gate (`72a0ec46`) treated as blocker evidence. The old
  `rho=1.18/V=6.6` / `174.600 W` screening basis is comparison-only; do not
  hard-stop or restart WO-006 from that old estimate unless the user explicitly
  asks for a sensitivity study.
- Do not claim `CD≈0.0315`, run AoA sweeps, or update design power until the
  OpenFOAM line has a same-family Coarse/Medium/Fine ladder with checkMesh,
  force histories, y+, Cp, Cf, wake, and tip-vortex comparisons.
- Latest Fine generator smoke `fine_te_fix_blend1_wake4_smoke` has repaired
  the previous open-cell blocker (`open cells=0`, `negative volumes=0`, max
  cell openness `4.98214e-14`) but still fails strict checkMesh with `100`
  lower-TE body/wake wrong-oriented face pyramids and `2` failed checks. With
  the data-authority checker prerequisite preserved, the next WO-006 OpenFOAM
  mesh task is finite-TE H-block/sleeve/interface topology, not restarting the
  old 3.77M open-cell diagnosis.

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
- WO-006 first bounded current-pathfinder attempt is complete with verdict
  `su2_baseline_needs_fix`. The current pathfinder VSP3 provider materializes,
  but default mesh handoff timed out in Gmsh volume insertion and coarse
  sensitivity failed boundary parametrization topology, so no usable
  current-pathfinder SU2 CL/CD delta exists yet.
- WO-006R1 current GO mesh-native bridge is complete with verdict
  `wo006r1_go_cfd_bridge_smoke_ready`. It writes a current-authority coarse
  no-BL `mesh_handoff.v1`, materializes a marker-owned SU2 case, and runs a
  3-iteration SU2 readability smoke. It is not yet CL/CD/CDi/profile-drag
  calibration evidence because the mesh is underresolved, lacks BL/y+, and
  coefficient sanity fails.
- WO-006R2 CFD recovery campaign is complete with verdict
  `wo006r2_current_geometry_adapter_blocker_isolated`. It reused the old
  1.125M-cell BL/HXT template and 1.515M-cell failure boundary, then adapted the
  route to current no-touch `avl_parity` GO geometry. The serious BL and
  high-mesh no-BL attempts now block at Gmsh HXT PLC / surface panel
  intersection, not at SU2 force/reference tuning. No interpretable CFD
  coefficient or Baseline A reopen evidence exists yet.
- WO-006R3 surface-topology repair is complete with verdict
  `wo006r3_high_mesh_handoff_ready`. It produced a current-GO high-mesh no-BL
  SU2 readability handoff with `936,017` volume cells and marker audit pass, but
  no BL/y+ handoff and no interpretable coefficient.
- WO-006R4 BL ownership repair is complete with verdict
  `wo006r4_adapter_limitation_proven`. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r4_bl_ownership_repair/`.
  The current adapter can build an owned near-wall BL block on current GO
  geometry without changing source shape, but it still cannot write a conformal
  BL+core SU2 handoff. Gmsh-owned BL remains blocked by DAE31-family PLC
  topology; remeshed-core workarounds are rejected because they change the
  BL-core interface. No coefficient is interpretable.
- WO-006R5 BL+core merge is complete with verdict
  `wo006r5_core_merge_limitation_proven`. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r5_bl_core_merge/`.
  The preserved-core probe keeps the core interface envelope, but core quality
  fails and BL/core coupling remains partial at `wake_cut` / `span_cap`; the
  all-non-wall BL boundary shortcut is not watertight. No conformal mixed
  BL+core SU2 handoff, no `bl_mesh_handoff.v1.json`, and no coefficient is
  interpretable.
- WO-006R6 core-interface repair is complete with verdict
  `wo006r6_core_quality_limitation_proven`. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/`.
  Preserved-core interface envelope exists, but core quality fails on
  non-positive elements and wake/span-cap coupling is not zero-unmatched. No
  coefficient is interpretable.
- WO-006R7 core-quality hotspot diagnosis is complete as a blocker-localization
  artifact. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r7_core_quality_hotspot_diagnosis/`.
  The R6 core quality failure is currently localized to 91 non-positive pyramid
  transition elements attached to the preserved `bl_outer_interface` quads; this
  points at the quad-to-tet transition/interface orientation, not solver
  iteration count.
- WO-006R8 basic airfoil BL sanity benchmark is complete as a simple-route
  diagnostic, not Baseline A evidence. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r8_basic_airfoil_bl_benchmark/`.
  The latest `solver_5000` run uses 2D `NACA4412`, HPA Reynolds scale, Gmsh BL
  quads, and SU2 `INC_RANS/SA` no-slip wall; it satisfies SU2 `Cauchy[CD] < 1e-6`
  at iteration `4597` with `CL=0.887615`, `CD=0.021682`, `CMz=0.100707`.
  Last-100-iteration `CL/CD/CMz` spans are about `0.0046%` / `0.0456%` /
  `0.0038%`, so this is useful route sanity evidence only, not Baseline A CFD
  evidence.
- WO-006R9 triangulated core-interface probe is complete as mesh-interface
  evidence, not CFD evidence. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r9_triangulated_core_interface_probe/`.
  It preserves the Baseline A BL/core boundary as triangles and HXT produces a
  clean all-tetra core (`6,005` cells, `pyramid=0`, no non-positive
  SICN/SIGE/volume). The remaining blocker is not the R7 bad-pyramid family;
  it is incomplete wake/span-cap BL/core coupling plus missing merged mixed SU2
  handoff.
- WO-006AD near-wall merged-volume candidate has been repaired after the R9
  read. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006ad_near_wall_merged_volume_candidate_probe/`.
  The layer-0 sharp-TE wall/wake seam stitch now removes the AD external-surface
  open-edge blocker (`bad_edge_count=0`, `remapped_node_count=66`) while keeping
  original Baseline A external shape unchanged. This is still not SU2 handoff:
  the next WO-006 repair, with the data-authority checker prerequisite
  preserved, should generate and quality-gate a core/farfield mesh from this
  watertight near-wall candidate, then only after marker/readability and y+
  checks attempt a coarse/medium/fine solver ladder.
- WO-006R10 near-wall core closure probe is complete as a topology/policy gate,
  not CFD evidence. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r10_near_wall_core_closure_probe/`.
  It confirms AD's full near-wall boundary is watertight, but the core-facing
  subset remains open (`64` bad edges) unless physical-wall roles are borrowed;
  that full-shell shortcut is forbidden because it would mis-own `wing_wall`
  and `physical_wall_edge_receiver` as core interface. The current edge-gap
  audit confirms all `64` core-facing open edges pair with
  `physical_wall_edge_receiver` (`60` tip pairs, `4` wake pairs,
  `unexplained_bad_edge_count=0`). With the data-authority checker prerequisite
  preserved, materialize a true core-facing
  closure without changing the external Baseline A wall shape, then generate a
  marker/quality-gated core/farfield mesh.
- WO-006I setup preflight now consumes the WO-006R10 core-closure artifact before
  any solver run. The current preflight summary is still
  `GOAL_STATUS=INCOMPLETE` / `CFD_STATUS=mesh_ladder_incomplete`, and its setup
  blockers include `near_wall_core_mesh_probe_missing` in addition to missing
  BL/y+ handoff. WO-006R11 now supersedes the R10 wall-edge dependency blocker
  by materializing two `32`-node core-facing loops into `64` cap faces with
  post-cap topology `watertight`; the next repair should generate and quality
  gate the core/farfield mesh from that loop-cap surface. Do not run medium/fine
  SU2 until this R11-derived mesh-probe blocker is repaired.
- WO-006R12 loop-cap core mesh probe is complete as blocker-localization
  evidence, not CFD evidence. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r12_loop_cap_core_mesh_probe/`.
  It uses the actual R11 `core_wall_loop_cap` surface as the core inner boundary,
  but Gmsh HXT core fill still blocks after about `96.6 s`: duplicate point
  filtering and self-intersecting facets expose a geometric PLC problem. The R12
  audit reports `70` exact duplicate-coordinate groups and `8` non-manifold
  bad edges after coordinate welding, concentrated at the tip/wake loop-cap seam
  across `wake_edge_receiver`, `core_wall_loop_cap`, and `core_tip_receiver_outer`.
  WO-006I setup preflight now reports this as
  `setup_near_wall_core_mesh_geometry_blocked`, superseding the older R10
  wall-edge-dependency blocker.
  Next repair should remove this sharp-TE/tip/wake geometric self-intersection
  before any merged BL/core handoff, y+, or SU2 ladder attempt.
- WO-006R13 loop-cap geometric seam repair is complete as core-mesh-probe
  progress, not CFD evidence. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r13_loop_cap_geometric_seam_repair_probe/`.
  It welds exact duplicate coordinates and removes `8` duplicate seam faces
  that collapse to the same marker/node set after welding. The repaired surface
  has `28,807` vertices / `2,860` faces, with zero duplicate-coordinate groups
  and zero welded bad edges. Gmsh HXT then produces a marker-owned core mesh:
  `29,993` nodes / `9,677` tetra cells, SU2 boundary ownership `pass`, and no
  non-positive SICN/SIGE/volume. Quality still carries very-low-shape warnings,
  and this is not a merged mixed BL+core SU2 handoff. WO-006R14 audits the
  R13 core surface against the near-wall volume handoff: `2800/2860` core
  polygons match, but only `1808/5658` active core triangles are conformal, and
  `60` `core_wall_loop_cap` polygons have no near-wall owner. WO-006R15 now
  checks the cheap repair hypothesis of splitting each near-wall hexa into two
  prisms and choosing the best diagonal per cell; it only matches `3166/5658`
  core triangles, leaving `bl_outer_interface=2048` unmatched. WO-006R16 expands
  that to all three split axes and reaches `5274/5658`, clearing
  `bl_outer_interface=2048` but still leaving `wake_edge_receiver=192`,
  `core_outer_edge_receiver=128`, `core_wall_loop_cap=60`, and
  `core_wake_outer_match=4`. WO-006R17 then allows local body-diagonal tet
  decompositions as well as prism splits and reaches `5590/5658`, clearing
  `core_outer_edge_receiver=128` and most wake/tip triangles. Remaining blockers
  are `core_wall_loop_cap=60` without candidate owner plus
  `wake_edge_receiver=4` / `core_tip_receiver_outer=4` incompatible owned
  triangles. WO-006R18 localizes that residual into two `core_wall_loop_cap`
  fans (`30` triangles each, near `y≈±17.201-17.202 m`) and two
  `tip_receiver/left_tip` cells (`26110`, `26111`) that each match `4/6`
  target triangles. WO-006R19 proves the loop-cap owner-pyramid basis:
  `60` physical-wall-edge receiver quads produce `60` owner pyramids, matching
  `60/60` `core_wall_loop_cap` triangles with no non-positive owner volume.
  WO-006I preflight treats the old direct-stageback PLC failure, R14
  generic mismatch, R15 single-axis prism split, and R16 prism-only split as
  superseded diagnostic evidence and advances to
  `setup_near_wall_hybrid_tet_prism_handoff_not_compatible`; the data-authority-restored mesh repair target is
  `repair_left_tip_receiver_shared_tessellation_then_write_loop_cap_owner_pyramid_mixed_mesh`
  before y+ probe or any solver ladder.
- WO-006F SU2 engineering-result recovery campaign is complete as a package with
  verdict `wo006f_campaign_incomplete`. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/`.
  No final physically credible SU2 CL/CD exists; no-BL RANS recovered lift with
  positive drag but `CD=0.5555196327` is far outside AVL/Tier2-profile/VSPAERO
  sanity bounds. R6 multizone can launch and remains the next route, but it is
  not force/coefficient evidence yet.
- WO-006H reopened CFD campaign is complete with verdict
  `su2_local_hard_limit_proven_with_executable_hpc_case`. Artifacts live in
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_reopened_cfd_campaign/`.
  It proves current-GO no-BL HXT can scale locally to `3,790,657` cells /
  `675,820` nodes with marker/quality pass, then finer no-BL probes fail at
  topology/PLC-style gates rather than memory exhaustion. BL/core variants still
  fail the conformal interface gate, so WO-006H is local hard-limit evidence
  plus an executable HPC case targeting the missing fine no-BL and BL/core
  routes, not aerodynamic calibration evidence.

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
| WO-006 | P1 | needs_fix | Main-Wing SU2 Baseline Validation | aero validation | With data-authority checker prerequisite preserved, reopened WO-006H reaches accepted `su2_local_hard_limit_proven_with_executable_hpc_case`, but no credible SU2 CL/CD; next repair/HPC execution must address fine no-BL topology, BL/core conformal topology, y+, force ownership, and grid V&V before any calibration claim |
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

Status: needs_fix after WO-006F SU2 engineering-result recovery campaign.

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

Current read: `su2_baseline_needs_fix`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/`. The current
pathfinder VSP3 uses the `98.5 kg` / `34.332286 m` authority basis, but the
default bounded mesh probe timed out in Gmsh 3D volume insertion and the coarse
sensitivity probe failed boundary parametrization topology. No current-pathfinder
`mesh_handoff.v1` or usable SU2 CL/CD/CDi/profile-drag delta exists yet. Treat
this as SU2 route repair evidence, not Baseline A reopen, release truth,
RFQ/procurement truth, structural sign-off, or final aircraft sign-off.

R1 read: `wo006r1_go_cfd_bridge_smoke_ready`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r1_go_cfd_bridge/`.
R1 selects the mesh-native route from current production-inspection
`section_table.csv` + `airfoils/*.dat`, writes marker-owned wing/farfield faces,
materializes a coarse HXT no-BL `mesh_handoff.v1` and SU2 case, and runs a
3-iteration solver readability smoke. The result is still not aerodynamic
calibration evidence: the mesh has only about 2.9k volume elements, no BL/y+, no convergence,
and coefficient sanity fails. Next work should upgrade the current GO mesh-native
route toward near-wall/BL quality and stable solver trends without changing
external shape, mass, CG, or span authority.

R2 read: `wo006r2_current_geometry_adapter_blocker_isolated`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r2_cfd_recovery_campaign/`.
R2 reused the old serious mesh-native evidence: the `wing_h=0.20 m` 1,125,409-cell
BL/HXT route as the primary template, the `wing_h=0.15 m` 1,515,251-cell failure
as the finer-boundary warning, and the 717,901-cell no-BL long run only as
solver/reference sign evidence. Current no-touch `avl_parity` GO geometry
remained fixed. The coarse control mesh succeeded, but serious BL and high-mesh
attempts hit Gmsh HXT PLC / surface panel intersections around section brackets
4-5 and 2-3. No SU2 coefficient is interpretable and Baseline A reopen remains
`not_evaluated`. Next work should localize and repair the current-GO surface
panel / tessellation adapter without changing external shape.

R3 read: `wo006r3_high_mesh_handoff_ready`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/`.
R3 repaired DAE31 near-TE loop ordering and produced the serious current-GO
high-mesh no-BL handoff (`936,017` volume cells, marker audit pass, SU2
readability to iteration 75). It is not BL/y+ evidence and no coefficient is
interpretable.

R4 read: `wo006r4_adapter_limitation_proven`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r4_bl_ownership_repair/`.
R4 compared the remaining Gmsh-owned BL blockers with a mesh-native owned-BL
block route. The owned-BL block has positive estimated volumes and a plausible
first-layer y+ basis, but the current adapter lacks a conformal BL+core merge and
mixed-element SU2 writer; preserved core probing fails quality/coupling, while
remeshed core probing hides the interface problem. No `bl_mesh_handoff.v1.json`
exists and no coefficient is interpretable.

R5 read: `wo006r5_core_merge_limitation_proven`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r5_bl_core_merge/`.
R5 keeps current authority data and external shape fixed. It proves the
preserved-core interface envelope can be kept without remeshing, but the core
mesh quality gate still fails and BL/core coupling remains partial at
`wake_cut` / `span_cap`. The direct all-non-wall BL boundary core-surface shortcut
is not watertight. No conformal mixed BL+core handoff exists, no
`bl_mesh_handoff.v1.json` exists, and no coefficient is interpretable.

R6 read: `wo006r6_core_quality_limitation_proven`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/`.
R6 preserved the core interface envelope but still failed core quality
(`non-positive SICN/SIGE/volume`) and did not close wake/span-cap coupling. It
does not provide y+, a merged BL+core SU2 handoff, or interpretable coefficients.

WO-006F read: `wo006f_campaign_incomplete`. Artifacts live in
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/`.
The campaign tried no-BL NS/RANS/Euler, OpenVSP/Gmsh, OpenVSP CFDMesh, and R6
BL/core multizone probes. SU2 did not produce a final physically credible CL/CD
pair: no-BL RANS was sign-correct (`CL=1.289421542`, `CD=0.5555196327`) but
too draggy and not converged, while Euler positive windows were not stable final
states. R6 multizone launches and is the best next route, but it remains route
evidence until core quality, wake/span-cap coupling, and coefficient ownership
are fixed.

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

With the data-authority checker prerequisite preserved, WO-006R9 is complete
enough to refine the next implementation target, but not enough to claim viscous
CFD. The completed artifact bundle is
`output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r9_triangulated_core_interface_probe/`.
Verdict: core quality is repaired for the R7 bad-pyramid family, but the route is
still blocked at wake/span-cap BL/core coupling and missing merged mixed SU2
handoff. No conformal BL+core SU2 handoff, `bl_mesh_handoff.v1.json`,
postprocessed y+, or interpretable coefficient exists.

The next recommended WO-006 task keeps the data-authority checker prerequisite
preserved and remains inside bounded aero calibration:
run `scripts/check_baseline_a_data_authority.py --check-only`, then materialize
the wake/span-cap receiver or envelope topology so the owned BL block and
triangulated core have zero unmatched internal faces. Do not spend medium/fine
runtime on the no-BL CD~0.5 path. Only after the topology, marker, and quality
gates pass should a mixed-element SU2 handoff be written.

```text
/goal In /Volumes/Samsung SSD/hpa-mdo, execute the next WO-006 repair after WO-006R9 with the data-authority checker prerequisite preserved: materialize the wake/span-cap receiver or BL/core envelope topology so the Baseline A owned BL block and triangulated core have zero unmatched internal faces, then write a mixed-element SU2 handoff only after topology, marker, and quality gates pass.

Read first:
- README.md
- CURRENT_MAINLINE.md
- docs/AI_WORK_ORDER_PROTOCOL.md
- docs/work_orders/QUEUE.md
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/route_decision.json
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/core_interface_repair_report.md
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/core_interface_topology_audit.json
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/mesh_quality_gate.json
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/interface_conformality_audit.csv
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r9_triangulated_core_interface_probe/
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r9_triangulated_core_interface_probe/triangulated_core_interface_summary.json
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r9_triangulated_core_interface_probe/triangulated_core_interface_report.md
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/
- hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/
- hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/
- hpa_meshing_package/docs/reports/hpa_main_wing_cfd_method_review/

Task:
Start from WO-006R9's blocker proof:
- triangulated preserved-core route keeps the interface envelope and clears core
  non-positive quality (`pyramid=0`, all-tetra core, no non-positive
  SICN/SIGE/volume);
- BL/core coupling remains partial at `wake_cut` / `span_cap`;
- the all-non-wall BL boundary shortcut remains not watertight in earlier R6
  evidence (`124 bad edges`);
- no final merged mixed-element SU2 handoff exists.

Allowed:
- preserve the repaired triangulated core-quality route without changing
  external shape;
- preserve `bl_outer_interface`, `wake_cut`, and `span_cap` ownership with zero
  unmatched interface faces;
- write a mixed-element SU2 mesh only after marker / quality / interface gates
  pass;
- keep Gmsh topological BL attempts as comparison/blocker evidence, not primary
  if the owned-BL route is cleaner.

Disallowed:
- changing external geometry authority files, mass/CG, span, Sref/Cref/Bref,
  spar/RFQ, procurement truth, or Baseline A release status;
- accepting no-BL coefficients as drag evidence;
- QPROP/XROTOR, full design-space CFD, vendor decisions, or final aircraft
  sign-off claims.

Required output:
- verdict: handoff-ready only if a real merged mesh exists; otherwise classify
  core-quality limitation vs interface-topology limitation with exact blockers
- exact authority basis used
- BL+core merge root-cause explanation in plain language
- merge / writer attempts accepted or rejected
- whether serious BL handoff materializes and whether `bl_mesh_handoff.v1.json`
  is emitted
- whether any SU2 coefficient is interpretable; normally no unless CFD evidence
  gate passes
- verification, engineering caveats, reviewer prompt, and next work order

Verification:
- run the WO-006R6 BL+core interface repair campaign or probes
- run targeted tests for changed code
- run `scripts/check_baseline_a_data_authority.py --check-only`
- run ruff on changed Python files
- run `git diff --check`
- use `git add -p` only for this work-order scope and commit
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
