# WO-006 CFD Problem / Solution Register

This register records the current Baseline A main-wing CFD blockers, known bad
paths, working repairs, and remaining unknowns.  It is not CFD completion
evidence; it is a handoff/debug map for the next worker.

## Current Gate

- Current geometry authority: Baseline A current GO geometry loaded through
  `load_campaign_geometry`, with full span `34.332286 m` / half span
  `17.166143 m`; mass authority remains `98.5 kg`.
- Latest topology/marker handoff: WO-006R27.
- Current CFD status: `mesh_ladder_incomplete`.
- Current active blockers after R27 preflight:
  - `physics_setup_is_no_bl_diagnostic`
  - `boundary_layer_mesh_missing`
  - `conformal_bl_core_handoff_missing`
  - `postprocessed_near_wall_yplus_missing`
  - `fewer_than_three_successful_rungs`
- Engineering read: R27 clears mixed-mesh marker/quality handoff for a bounded
  solver route-smoke. It does not clear solver physics, force-history stability,
  CD-order sanity, or grid convergence.

## Problems And Repairs

| Problem | Symptom / bad evidence | Root cause found | Working repair / current method | Remaining gate |
|---|---|---|---|---|
| no-BL or wrong wall setup being mistaken for CFD | finite CL/CD existed, but prior no-BL / poor BL cases produced `CD≈0.4-0.6`, far above expected HPA main-wing `0.0XX` drag order | solver could produce finite numbers on invalid near-wall physics | WO-006R8 basic NACA4412 BL sanity: Gmsh BL quads + SU2 `INC_RANS/SA` + no-slip `MARKER_HEATFLUX` gave `CL=0.8876`, `CD=0.02168`; WO-006I gates reject no-BL completion | Use R27 mesh in a wall-resolved SU2 config, then check force stability and CD-order sanity |
| direct stageback route PLC failure | Gmsh `PLC Error` / segment-facet intersection on no-BL-hole stageback attempts | direct stageback topology collides with current GO transition/tip geometry | Treat stageback route as historical diagnostic once core/mixed handoff artifacts exist | Do not revive direct stageback unless R27 route fails for a reason tied to that topology |
| R13 core mesh was not enough for mixed handoff | core/farfield mesh could pass marker/quality alone, but BL/core interface was not conformal | core surface and near-wall candidate had incompatible boundary triangulation/ownership | R14-R20 localized residuals; R19 loop-cap owner pyramids and R20 left-tip star cells provided local repair bases | Superseded by R22/R24/R27 path; keep as provenance |
| local split choices created internal nonconformality | R21 found `7960` internal split leaks and `64` nonmanifold split faces | per-cell local best split does not guarantee global cell-to-cell conformality | R22 global center-star split with deterministic internal face treatment | Superseded by R24/R27 path |
| degenerate global-star triangles | R22 had `128` zero-area star triangles | all degenerate triangles were empty-marker wake-receiver zero-area faces | R23 localized them to `32` wake_receiver cells; R24 proved they can be culled without losing owned markers | Done for R27 handoff basis |
| R25 mixed SU2 handoff had unmarked exterior faces | R25 wrote `332,221` tets with volume quality pass, but marker audit failed: `68` unmarked exterior faces, area `0.075898249 m^2` | loop-cap / wake-edge closure faces existed as exterior volume faces without final SU2 marker ownership | R26 classified all `68` faces: `60` loop-cap owner pyramid exterior, `4` physical-wall-edge closure, `2` candidate wake-edge, `2` core wake-edge; no unclassified faces | R27 applied the repair |
| R26 repair plan not applied yet | WO-006I preflight saw `near_wall_mixed_su2_boundary_marker_repair_not_applied` | R26 only created a repair plan; R25 writer still emitted the old marker set | R27 applies only R26 records with `recommended_marker=wing_wall` and rewrites the mixed SU2 handoff | Done: R27 marker audit pass |
| old blocked artifacts overriding newer pass artifacts | WO-006I saw R27 pass artifact but still reported R26/R25 blocker | artifact aggregation overwrote a newer pass with older blocked records | make mixed handoff readiness cumulative and preserve the first/ready handoff record | Done in WO-006I gate tests |

## R27 Current Evidence

- Script: `scripts/probe_wo006r27_apply_boundary_marker_repair.py`
- Artifact: `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r27_apply_boundary_marker_repair_probe/`
- Repaired mesh: `culled_global_star_mixed_handoff_r27_repaired.su2`
- Nodes / volume elements: `56,873` / `332,221`
- Element types: all tetra (`10`)
- Markers: `wing_wall=1992`, `farfield=2366`
- Boundary marker audit: pass
  - boundary faces: `4358`
  - marked boundary faces: `4358`
  - unmarked faces: `0`
  - extra marker faces: `0`
  - duplicate marker faces: `0`
  - nonmanifold volume faces: `0`
- Mixed volume quality: pass
  - non-positive volumes: `0`
  - min volume: `1.96233350787495e-12 m^3`
  - max volume: `122.24077255800682 m^3`
- Near-wall estimate: first layer `5e-5 m` gives estimated `y+≈1.04` for the
  current GO mean chord; this is not solver-postprocessed y+.

## Known Unknowns

- Whether SU2 reads the R27 repaired mixed mesh without parser/marker issues.
- Whether the first R27 route-smoke force history is stable over a real
  100-iteration window.
- Whether CD returns to plausible HPA main-wing order (`0.0XX`) or still shows
  pressure/BC/domain pathology.
- Whether the R27 marker repair scales cleanly to larger coarse/medium/fine
  mesh rungs.
- Whether solver-postprocessed y+ remains acceptable across the full wing,
  especially tip/wake/loop-cap closure regions.

## Next Repair / Run Order

1. Wire the R27 repaired SU2 mesh into a bounded route-smoke config using
   `INC_RANS`, `SA`, `MARKER_HEATFLUX=(wing_wall,0.0)`, `MARKER_FAR=(farfield)`,
   and `INC_NONDIM=INITIAL_VALUES`.
2. Run a short but not toy smoke only to verify SU2 reads the mesh, markers, and
   references.
3. If finite, continue long enough to get at least a 100-iteration force window.
4. Reject the result if `CD > 0.15` for the HPA main-wing case, even if residuals
   are finite.
5. Only after route-smoke passes marker, y+, force-stability, and CD-order gates,
   attempt a coarse/medium/fine ladder.

