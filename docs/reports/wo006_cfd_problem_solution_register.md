# WO-006 CFD Problem / Solution Register

This register records the current Baseline A main-wing CFD blockers, known bad
paths, working repairs, and remaining unknowns.  It is not CFD completion
evidence; it is a handoff/debug map for the next worker.

## Current Gate

- Current geometry authority: Baseline A current GO geometry loaded through
  `load_campaign_geometry`, with full span `34.332286 m` / half span
  `17.166143 m`; mass authority remains `98.5 kg`.
- Latest solver-facing probe: WO-006R28.
- Current CFD status: `mesh_ladder_incomplete`.
- Current active blockers after R28 route smoke:
  - `su2_dual_orthogonality_angle_extreme`
  - `su2_dual_cv_face_area_aspect_ratio_extreme`
  - `su2_dual_cv_sub_volume_ratio_extreme`
  - `route_smoke_cd_implausibly_high_for_hpa_main_wing`
  - `coarse_medium_fine_solver_ladder_not_run`
- Engineering read: R27 cleared marker ownership, but R28 showed the repaired
  mesh is not CFD usable yet.  SU2 can read the mesh/markers, but solver-side
  dual-control-volume quality is pathological; medium/fine ladder runs are
  blocked until the BL/core transition sizing and dual-volume quality are
  repaired.

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
| solver-side dual-volume quality is pathological | R28 FDS/MUSCL route-smoke diverged at iteration `5`; SU2 log reports min orthogonality angle `0.00108069 deg`, max CV face-area aspect ratio `5.15199e8`, and max CV sub-volume ratio `2.07841e11` | R27 only checked positive primal tetra volume / marker ownership; it did not control the BL/core transition cell-size jump or SU2 dual-control-volume quality | R28 now parses SU2 mesh-quality lines from `solver.log` and blocks ladder promotion when dual metrics are extreme | Localize and repair the BL/core transition sizing / mixed-mesh quality before any medium/fine ladder |
| conservative numerics can run but do not make the mesh credible | R28 JST, `MUSCL_FLOW=NO`, `CFL=0.02` completed `180` iterations but ended at `CL=0.6908`, `CD=0.3916`, `Cm=-0.1424`; last-100 force and residual stability both failed | Lower-order numerics can avoid immediate divergence, but high drag and unstable forces persist on the same pathological dual mesh | Use conservative numerics only as diagnostic evidence; do not treat finite coefficients as route success | Fix mesh quality first; then rerun wall-resolved route-smoke and require `CD <= 0.15` plus 100-iteration force stability |

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

## R28 Current Evidence

- Script: `scripts/probe_wo006r28_r27_su2_route_smoke.py`
- Tests: `tests/test_wo006r28_r27_su2_route_smoke_probe.py`
- FDS/MUSCL artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r28_r27_su2_route_smoke_probe_solver180/`
  - SU2 setup: `INC_RANS`, `SA`, `INC_NONDIM=INITIAL_VALUES`,
    `MARKER_HEATFLUX=(wing_wall,0.0)`, `MARKER_FAR=(farfield)`
  - marker/config audit: pass (`wing_wall`, `farfield`)
  - solver status: failed at iteration `5` with SU2 divergence
  - history coefficients at failure: `CL≈1.73e16`, `CD≈-2.66e16`,
    `Cm≈-5.62e16`
  - resource trace: `/usr/bin/time -l`, peak RSS about `885 MB`
  - SU2 dual quality: min orthogonality `0.00108069 deg`, max CV face-area
    aspect ratio `5.15199e8`, max CV sub-volume ratio `2.07841e11`
- Conservative JST diagnostic artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r28_r27_su2_route_smoke_probe_jst_cfl002_solver180/`
  - numerics: `CONV_NUM_METHOD_FLOW=JST`, `MUSCL_FLOW=NO`, `CFL=0.02`
  - solver status: completed `180` rows / final iteration `179`
  - final coefficients: `CL=0.6907996374`, `CD=0.3916369149`,
    `Cm=-0.1423905686`
  - last-100 force stability: fail (`CL` spread `1.19`, `CD` spread `0.94`,
    `Cm` spread `0.120`)
  - residual stability: fail (`rms[P/U/V/W]` worsening)
  - engineering read: conservative numerics can keep the route alive, but the
    same solver-side mesh-quality blocker and implausible CD remain.

## Known Unknowns

- Exact geometric location/source of the SU2 dual-control-volume quality
  extrema.
- Whether repairing BL/core transition sizing is sufficient, or whether the
  loop-cap / wake closure topology must also be reshaped.
- Whether the R27 marker repair scales cleanly to larger coarse/medium/fine
  mesh rungs.
- Whether solver-postprocessed y+ remains acceptable across the full wing,
  especially tip/wake/loop-cap closure regions.

## Next Repair / Run Order

1. Localize the R28 SU2 dual-control-volume quality extrema back to R27 mixed
   mesh sources: near-wall global-star cells, loop-cap owner pyramids, or core
   tetra cells.
2. Repair the BL/core transition sizing / mixed-mesh quality so SU2 dual metrics
   are no longer pathological.
3. Rerun R28 route-smoke with the wall-resolved config and require marker audit
   pass, finite CL/CD/Cm, `CD <= 0.15`, and at least a 100-iteration force
   stability window.
4. Only after route-smoke passes marker, y+, force-stability, and CD-order gates,
   attempt a coarse/medium/fine ladder.
