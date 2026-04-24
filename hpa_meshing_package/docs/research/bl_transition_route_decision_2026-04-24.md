# BL Transition Route Decision - 2026-04-24

## Executive Summary

Decision: choose feasibility class **3 - locally feasible, but the tip-terminal BL should terminate early and hand off to a tetra/core transition**.

The current `shell_v4` real-wing BL route is not a simple parameter-policy problem. The evidence is more consistent with a transition-topology handoff problem at the post-band / tip-terminal region. Gmsh is receiving a local PLC made from BL-extruded surfaces, a connector band, and a termination ring that does not yet prove a legal segment/subface/receiver-face graph. Once the older overlap family is removed, the remaining family reaches Gmsh boundary recovery and fails in `addsteiner4recoversegment:failed_insert_steiner`, which is a late-stage constrained-segment recovery failure, not a clean "use one fewer BL layer" signal.

The current uncontracted local route should stop being tuned by layer count, truncation start, or guard y alone. The next route should keep `shell_v4` as the active validation branch, keep `shell_v3` frozen, and introduce an explicit BL-to-core transition topology contract or sleeve. Gmsh should then receive a closed, topology-preserving interface rather than being asked to infer the BL termination topology.

Recommended next branch:

```text
codex/shell-v4-bl-transition-sleeve-contract
```

Recommended first two commits for the next round:

1. `docs: define shell_v4 BL transition topology contract`
2. `test: add report-only BL transition ring graph fixtures`

Do not run another BL candidate sweep until the route can produce and validate a formal transition ring / receiver-face / BL-to-core interface artifact.

## Evidence Reviewed

### hpa-mdo files

- `hpa_meshing_package/src/hpa_meshing/shell_v4_half_wing_bl_mesh_macsafe.py`
- `hpa_meshing_package/src/hpa_meshing/compiler/__init__.py`
- `hpa_meshing_package/src/hpa_meshing/compiler/compiler_v1.py`
- `hpa_meshing_package/src/hpa_meshing/compiler/motif_registry_v1.py`
- `hpa_meshing_package/src/hpa_meshing/compiler/operator_library_v1.py`
- `hpa_meshing_package/src/hpa_meshing/compiler/pre_plc_audit_v1.py`
- `hpa_meshing_package/src/hpa_meshing/compiler/topology_ir_v1.py`
- `hpa_meshing_package/docs/topology_compiler_architecture_2026-04-23.md`
- `hpa_meshing_package/docs/contracts/topology_ir.v1.md`
- `hpa_meshing_package/docs/contracts/motif_registry.v1.md`
- `hpa_meshing_package/docs/contracts/operator_library.v1.md`
- `hpa_meshing_package/docs/contracts/pre_plc_audit.v1.md`
- `hpa_meshing_package/docs/contracts/mesh_handoff.v1.md`
- `hpa_meshing_package/docs/contracts/su2_handoff.v1.md`

### hpa-mdo focused artifacts

- `.tmp/root_last3_failed_steiner_validation_c9af7c9/topology_bl_handoff_summary.v1.json`
- `.tmp/root_last3_failed_steiner_validation_c9af7c9/boundary_recovery_regularization/post_transition_boundary_recovery_regularization_report.json`
- `.tmp/bl_candidate_parameter_sweep_diagnostic_actual/artifacts/topology_compiler/bl_candidate_parameter_sweep/bl_candidate_parameter_sweep.v1.json`
- `.tmp/bl_candidate_parameter_sweep_actual/artifacts/topology_compiler/bl_candidate_parameter_sweep/bl_candidate_parameter_sweep.v1.json`
- `hpa_meshing_package/.tmp/stage_guard_apply_validation/artifacts/topology_compiler/staged_transition_apply/staged_transition_apply_comparison.v1.json`
- `hpa_meshing_package/.tmp/stage_guard_apply_validation/latest_summary.json`
- `hpa_meshing_package/.tmp/topology_compiler_plan_only_smoke/artifacts/topology_compiler/topology_compiler_summary.v1.json`
- `hpa_meshing_package/.tmp/topology_compiler_plan_only_smoke/artifacts/topology_compiler/pre_plc_audit.v1.json`
- `hpa_meshing_package/.tmp/topology_compiler_plan_only_smoke/artifacts/topology_compiler/motif_registry.v1.json`
- `hpa_meshing_package/.tmp/topology_compiler_plan_only_smoke/artifacts/topology_compiler/operator_plan.v1.json`

The loop-continuity diagnostic and staged-transition prototype writer exist in code as report-only contracts, but I did not find persisted `bl_stageback_loop_continuity_diagnostic.v1.json` or `bl_topology_preserving_staged_transition_prototypes.v1.json` files in this checkout. The decision below therefore uses the persisted sweep/apply artifacts plus the code contract for those report types.

### Gmsh source tree

I found all candidate source locations:

- `/private/tmp/gmsh-forensics`
- `/tmp/gmsh-forensics`
- `/Volumes/Samsung SSD/external-src/gmsh`

The first two are on branch `br-debug-visibility-a2-c` and contain the BR-debug visibility commits:

- `d59993fcb` (BR-debug fail-safe visibility patch)
- `6b9b11fdd` (BR-debug visibility patch)

I used `/private/tmp/gmsh-forensics` as the primary forensic worktree. `/Volumes/Samsung SSD/external-src/gmsh` is not suitable as the decision source because its worktree is heavily deleted/dirty and does not carry the same forensic branch state.

Gmsh files read:

- `/private/tmp/gmsh-forensics/src/mesh/meshGRegionBoundaryRecovery.cpp`
- `/private/tmp/gmsh-forensics/src/mesh/tetgenBR.cxx`
- `/private/tmp/gmsh-forensics/src/mesh/tetgenBR.h`
- `/private/tmp/gmsh-forensics/src/mesh/meshGRegionExtruded.cpp`
- `/private/tmp/gmsh-forensics/src/mesh/meshGRegion.cpp`
- `/private/tmp/gmsh-forensics/src/mesh/meshGRegionHxt.cpp`
- `/private/tmp/gmsh-forensics/src/mesh/meshGRegionHxt.h`
- `/private/tmp/gmsh-forensics/contrib/hxt/tetMesh/src/hxt_tetMesh.c`
- `/private/tmp/gmsh-forensics/contrib/hxt/tetBR/src/hxt_boundary_recovery.cxx`
- `/private/tmp/gmsh-forensics/contrib/hxt/tetBR/include/hxt_boundary_recovery.h`

## Current Failure Chain

The best current causal model is:

```text
raw real-wing tip geometry
  -> thin local upper/lower clearance near the tip terminal
  -> connector band / truncation transition
  -> BL layer extrusion and stageback
  -> termination ring / loop closure / receiver-face ambiguity
  -> prism or segment/subface handoff inconsistency
  -> Gmsh PLC boundary recovery
  -> failed Steiner insertion, segment-facet regression, or 1D loop failure
```

The strongest root-cause model is **hpa-mdo handoff topology contract insufficient**, with two concrete sub-failures:

1. **Tip-terminal termination ring and receiver-face ambiguity.** Removed or staged-back BL layers do not have a proven legal receiver face / sleeve. This is why 8 -> 7 can be topology-safe but insufficient, 8 -> 6 can reopen segment-facet, and 8 -> 5 can fail before 3D as a loop-closure family.
2. **Prism collapse upstream of boundary recovery.** `degenerated_prism_seen=true` remains tied to the same local y band as failed-Steiner evidence. That does not prove every boundary-recovery error is caused by prism collapse, but it strongly suggests both symptoms share the same upstream transition topology pressure.

Other root-cause candidates are secondary:

- **Clearance budget shortage:** strongly present, but not sufficient as the only explanation. If it were only budget, 8 -> 7 / truncation variants should show monotonic improvement. They do not.
- **Transition loop not closed:** proven for `stageback_only_layers5`, but not for guarded 8 -> 7, which still fails. So loop closure is a necessary check, not the full contract.
- **Non-manifold connector band:** plausible, but the first connector-band operator already consumed the original overlap family. The remaining family sits later, in post-band / tip-terminal transition.
- **Gmsh/TetGen-BR limitation:** present as a practical limitation, but it is triggered by a hard input topology. The correct response is to present Gmsh with a valid BL-to-core interface, not to expect BR to infer one.

## Gmsh Source Constraints

Gmsh/TetGen boundary recovery assumes the input can be represented as a valid 3D PLC:

- `tetgenBR.h:260-265` describes a tetrahedral mesh of a 3D PLC with a 2D boundary subcomplex `S` and 1D boundary subcomplex `L`; faces and edges in these complexes are explicitly stored as subfaces and segments.
- `tetgenBR.h:304-311` gives each subface adjoining subfaces, vertices, adjoining segments, and two adjoining tetrahedra.
- `meshGRegionBoundaryRecovery.cpp:577-637` creates TetGen subfaces from GFace triangles, creates segment records for triangle edges, then calls `unifysegments()`.
- `meshGRegionBoundaryRecovery.cpp:647-723` maps Gmsh edges into subsegments. If a constrained edge cannot be found on a subface, the code can create a dangling segment.
- `meshGRegionBoundaryRecovery.cpp:739-743` then enters boundary recovery.
- `tetgenBR.cxx:14975-15247` recovers segments first, then subfaces. Segment recovery escalates from flips, to fullsearch flips, to volume Steiner points, to segment splitting.
- `tetgenBR.cxx:12695-12861` shows `addsteiner4recoversegment()` as the fallback for missing segment recovery. The observed label `addsteiner4recoversegment:failed_insert_steiner` is thrown when a midpoint Steiner point on a missing segment cannot be inserted with boundary-respecting flags.
- `meshGRegionBoundaryRecovery.cpp:1366-1443` only emits the richer "Invalid boundary mesh" text when `sevent.e_type` is populated. If `sevent.e_type=0`, it falls back to `Could not recover boundary mesh: error 2`.

Interpretation:

`failed_insert_steiner` is not a normal geometry-quality warning. It means boundary recovery has already failed to recover a constrained segment through flips/fullsearch and could not legally split that segment either. In route terms, this is exactly what happens when the BL termination interface contains an overconstrained, ambiguous, or degenerate local segment/subface graph.

The degenerated-prism signal is compatible with the same upstream issue:

- `meshGRegionExtruded.cpp:51-82` creates tetrahedra or pyramids when extruded prism vertices duplicate, and warns on degenerated prism. That is an extrusion-side collapse before later PLC recovery. If the collapsed prism sits in the same terminal band as a missing constrained segment, the two failures are likely different downstream views of the same bad BL transition topology.

HXT is not a clean escape hatch:

- `meshGRegion.cpp:113-115` routes `ALGO_3D_HXT` to HXT.
- `hxt_tetMesh.c:110-153` checks missing triangles/lines, calls `hxt_boundary_recovery()`, then errors if boundary faces or constrained edges are still missing.
- `hxt_boundary_recovery.cxx:82-87` includes the same `tetgenBR.h` / `tetgenBR.cxx`.
- `hxt_boundary_recovery.cxx:271-395` rebuilds subfaces/subsegments from triangles/lines and then calls `recoverboundary()`.

So HXT can be used as a diagnostic comparison, but it does not remove the need for a valid transition PLC.

## Why Parameter Sweep Is No Longer Enough

The current data is not monotonic with parameter changes:

- `stageback_only_layers7`: still `boundary_recovery_error_2_recoversegment_failed_insert_steiner`; verdict `insufficient_still_failed_steiner`.
- `stageback_only_layers6`: reintroduces `segment_facet_intersection`; verdict `too_aggressive_reintroduces_segment_facet`.
- `stageback_only_layers5`: classified as `stageback_induced_1d_loop_closure_failure`; it fails before the useful 3D boundary-recovery stage.
- `truncation_only_y15p875`, `y16p000`, `y16p250`: still failed-Steiner.
- `truncation_only_y16p500`: reintroduces segment-facet.
- mild/strong combined stageback + truncation mostly reintroduces segment-facet or remains insufficient.
- guarded staged transition `stage_with_termination_guard_8_to_7`: loop/connector continuity is inferred safe, but the residual family, y band, suspicious window, and degenerated-prism flag are unchanged.

That pattern is not "find the right parameter." It is "the interface topology is not formally defined."

## Feasibility Verdict

### A. Route feasibility class

Selected class: **3. Locally feasible, but tip-terminal BL should terminate early and switch to tetra/core transition.**

Reason:

- The route has useful local machinery: topology compiler, observed family fixtures, connector-band operator, failed-Steiner forensic localization, BL budgeting, and default-off focused apply gates.
- But the current local transition/termination ring does not prove a legal Gmsh PLC handoff. Even the topology-safe guarded 8 -> 7 experiment leaves the failed-Steiner residual unchanged.
- The tip terminal has a severe clearance mismatch. The handoff summary reports terminal section clearance ratios around `0.137` to `0.145` for the top manual candidates, with the same families recommending shrink/thickness split/stageback/truncation. A full BL-to-tip policy is not credible unless a sleeve/receiver topology is explicitly generated.
- Gmsh source constraints make it unlikely that raw boundary recovery can infer the missing receiver topology.

Class 2 is close, but too optimistic for the current route because a contract alone must also change the handoff: the terminal BL should not continue as an implicit Gmsh-recovered termination. Class 4 is too pessimistic because Gmsh can still be used for the core tetra once hpa-mdo provides a clean BL-to-core interface.

### B. Current route topology answer

The current `shell_v4` route is **not yet topologically established** at the real-wing tip-terminal BL transition.

It can become viable if hpa-mdo owns the BL transition topology before Gmsh sees it. The minimum formal contract is:

- one or more explicit transition ring graphs, ordered in span and orientation
- closed-loop guarantee for every ring and terminal sleeve boundary
- layer-drop schedule with no direct deep drop like 8 -> 5
- receiver-face map for every removed/staged layer
- explicit BL-to-core interface block or termination sleeve
- no dangling constrained segments
- no segment/subface ambiguity after triangulation
- surface/edge role labels that do not rely on unstable surface IDs
- clearance budget gate that can say "terminate BL here" before extrusion
- pre-3D artifact proving valence, loop closure, receiver faces, and segment/subface ownership before any Gmsh `generate(3)`

## Route Options

### Route 1 - Keep Gmsh, add topology-preserving BL transition contract

Summary:

Keep Gmsh as the mesher, but require `shell_v4` to emit and validate a formal transition topology contract before any focused apply.

Expected contract elements:

- `transition_ring_graph`
- `closed_loop_count`
- `ring_orientation`
- `layer_drop_schedule`
- `layer_drop_receiver_faces`
- `termination_sleeve_faces`
- `bl_to_core_interface_surfaces`
- `segment_subface_valence_report`
- `no_dangling_segments`
- `clearance_budget_verdict`

Comparison:

- Implementation complexity: medium
- Risk: medium
- Expected robustness: medium-high if the contract is real, medium if it stays report-only
- Code reuse: high. Reuses compiler, pre-PLC fixtures, BL budgeting, and existing focused probes
- Avoids failed-Steiner trap: partially. It prevents blind handoff, but Gmsh still recovers the final volume boundary
- Next 1-2 commits:
  - `docs: define shell_v4 BL transition topology contract`
  - `test: add report-only BL transition ring graph fixtures`
- Stop condition:
  - If the contract cannot prove receiver faces and closed loops for the current tip-terminal transition, stop and move to Route 2 or Route 3.

### Route 2 - Semi-structured local BL block / sleeve generator

Summary:

hpa-mdo generates a small semi-structured local transition sleeve around the terminal BL handoff, then passes only a clean BL-to-core interface to Gmsh for core tetra. Gmsh no longer guesses the BL termination topology.

Comparison:

- Implementation complexity: medium-high
- Risk: medium
- Expected robustness: high
- Code reuse: medium-high. Reuses section lineage, BL budgeting, topology compiler role labels, and focused fixture families; adds a new sleeve materializer
- Avoids failed-Steiner trap: yes, if the sleeve emits a closed interface and removes dangling/missing receiver segments before Gmsh
- Next 1-2 commits:
  - `docs: define shell_v4 BL transition sleeve handoff`
  - `feat: emit report-only sleeve topology fixture without runtime apply`
- Stop condition:
  - If the sleeve cannot satisfy closed-loop/valence/receiver-face checks on the root_last3 fixture without surface-ID patches, do not continue implementing runtime apply.

This is the recommended primary route.

### Route 3 - Conservative tip-zone BL termination with tetra/core fallback

Summary:

Stop BL before the terminal tip zone and use tetra refinement or wall-adjacent fallback in the terminal region. This sacrifices local BL fidelity near the extreme tip to get solver-entry robustness on the Mac-safe validation route.

Comparison:

- Implementation complexity: low-medium
- Risk: low for meshing, medium for CFD interpretation
- Expected robustness: high
- Code reuse: high. Reuses current truncation analysis, BL budgeting, and named tip refinement
- Avoids failed-Steiner trap: yes, if termination happens inboard of the failed-Steiner band and the handoff surface is closed
- Next 1-2 commits:
  - `docs: define shell_v4 tip-terminal BL cutoff policy`
  - `test: add report-only cutoff gate for terminal BL fallback`
- Stop condition:
  - If solver-entry requires wall-resolved BL exactly through the terminal tip for the validation objective, this fallback becomes a diagnostic route, not the main validation route.

This is the fastest fallback if Route 2 is too large for the next sprint.

### Route 4 - HXT or alternate core tetra route

Summary:

Try HXT, CGAL, or another tetra core only after the BL transition handoff is made explicit.

Comparison:

- Implementation complexity: low for an HXT smoke, high for a real alternate core
- Risk: high if treated as a fix
- Expected robustness: unknown
- Code reuse: medium
- Avoids failed-Steiner trap: not by itself. HXT still performs boundary recovery and includes the same TetGen BR source path
- Next 1-2 commits:
  - `test: add optional HXT diagnostic comparison for explicit sleeve input`
  - `docs: record alternate core mesher acceptance criteria`
- Stop condition:
  - If HXT is used on the current uncontracted input and merely changes error text, do not treat that as route progress.

Route 4 should remain diagnostic, not the main decision path.

## Recommended Route

Recommended primary route: **Route 2 - semi-structured local BL block / sleeve generator**, with Route 1 as the required contract layer and Route 3 as the conservative fallback policy.

This is the cleanest engineering split:

- hpa-mdo owns BL termination topology.
- Gmsh owns core tetra meshing after the BL-to-core interface is legal.
- The Mac-safe validation route can still reach solver-entry without pretending terminal-tip BL fidelity is solved.
- The existing topology compiler remains useful as a planning and fixture layer.

The next round should not add a new topology operator immediately. It should first define and validate the contract that any future operator/sleeve must satisfy.

## No-go / Continue Criteria

### Continue criteria

Continue local `shell_v4` work only when all are true:

- the change is report-only, contract-only, or behind an explicit default-off experimental gate
- `shell_v3` remains untouched
- production defaults remain unchanged
- no surface-ID patch is used as the selector
- the transition artifact proves loop closure, ring orientation, receiver faces, and segment/subface valence
- focused rerun evidence shows no regression to `segment_facet_intersection`
- failed-Steiner evidence is removed, or at least local y band / suspicious window / degenerated-prism evidence improves monotonically

### No-go criteria

Stop tuning the current local route when any of these occur:

- `boundary_recovery_error_2_recoversegment_failed_insert_steiner` stays unchanged after a topology-safe candidate
- a candidate reintroduces `segment_facet_intersection`
- a candidate fails before 3D as `stageback_induced_1d_loop_closure_failure`
- `degenerated_prism_seen=true` persists in the same local terminal band
- the route cannot name receiver faces for removed/staged layers
- the route requires unstable surface tags to decide where to patch
- the BL clearance ratio in the terminal band stays far below 1.0 and no explicit BL cutoff/sleeve exists

### Branch-switch criteria

Switch from current-route tuning to a new meshing/handoff branch when:

- two safe variants leave failed-Steiner unchanged
- one deeper variant reopens segment-facet while a shallower variant is insufficient
- loop closure fails before 3D for the next deeper stageback
- Gmsh source forensics points to constrained segment recovery rather than a plain overlap/self-intersection event
- HXT/TetGen-style boundary recovery would still receive the same uncontracted segment/subface graph

The current evidence already satisfies these branch-switch criteria.

### Minimum evidence required before runtime apply

Before any new candidate is allowed to affect runtime, require:

- `bl_transition_topology_contract.v1` artifact
- transition ring graph with closed loops and orientation
- receiver-face ownership for every layer drop
- BL-to-core interface block/sleeve faces
- no dangling constrained segments
- local clearance and BL thickness budget verdict
- focused fixture pre-3D check
- one focused 3D boundary-recovery probe showing no failed-Steiner and no segment-facet regression
- explicit non-regression on root_last4 overlap

Full prelaunch is not required for the first proof, but the local contract must pass before a full prelaunch is worth running.

## Next Two Commits

### Commit 1

Message:

```text
docs: define shell_v4 BL transition topology contract
```

Content:

- Add `hpa_meshing_package/docs/contracts/bl_transition_topology.v1.md`.
- Define ring graph, receiver faces, sleeve/interface blocks, valence checks, clearance gate, and default-off apply semantics.
- Explicitly state that this contract is a precondition for any new topology operator, BL candidate apply, HXT comparison, or full prelaunch.

Acceptance:

- No code changes required.
- Contract maps directly to current artifact names and failure families.
- It forbids shell_v3 mutation, production default mutation, and surface-ID patches.

### Commit 2

Message:

```text
test: add report-only BL transition ring graph fixtures
```

Content:

- Add a report-only fixture validator for `root_last3` and root_last4 non-regression.
- It should consume existing section-lineage / topology compiler data and emit a ring/receiver-face validation artifact.
- It should not apply geometry mutations.

Acceptance:

- Fixture can classify current route as failing the receiver-face/sleeve contract.
- It preserves the current `off` / `plan_only` semantics.
- It gives the next implementation step an explicit target instead of another parameter sweep.

## Things Explicitly Not To Do

- Do not change `shell_v3`.
- Do not change production defaults.
- Do not run another BL candidate sweep as the next action.
- Do not chase a full prelaunch pass before the local transition contract exists.
- Do not auto-apply `stageback_plus_truncation` or guarded staged transition.
- Do not patch by surface ID.
- Do not promote HXT as a fix for the current uncontracted PLC.
- Do not treat `sevent_e_type=0` as weak evidence that nothing happened. In this case the throw-site label is the useful forensic evidence.
- Do not call a loop-closed guarded transition successful when the failed-Steiner family, y band, suspicious window, and degenerated-prism signal are unchanged.

## Final Engineering Judgment

We are facing a **transition topology architecture problem**, not a parameter problem.

The current `shell_v4` machinery is valuable and should be kept, but the route must move one level up: define the BL transition topology, validate it, and only then let Gmsh recover the core tetra boundary. The recommended next route is a semi-structured local BL transition sleeve or, if speed matters more than fidelity, an inboard terminal BL cutoff with tetra/core fallback. Both are more engineering-rational than another layer/truncation/guard sweep.
