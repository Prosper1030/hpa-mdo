# WO-006 CFD Problem / Solution Register

This register records the current Baseline A main-wing CFD blockers, known bad
paths, working repairs, and remaining unknowns.  It is not CFD completion
evidence; it is a handoff/debug map for the next worker.

## Current Gate

- Current geometry authority: Baseline A current GO geometry loaded through
  `load_campaign_geometry`, with full span `34.332286 m` / half span
  `17.166143 m`; mass authority remains `98.5 kg`.
- Active CFD delivery route: `canonical_hybrid_halfwing_v0`.
- Active route state:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/manifest.yaml`.
- Route-policy checker: `scripts/check_canonical_hybrid_cfd_release.py`.
- External rescue reference:
  `docs/reports/wo006_cfd_external_rescue_reference.md`.
- Forensic-only routes: WO-006R25, WO-006R26, WO-006R27, WO-006R28,
  WO-006R29, WO-006R30.
- Latest solver-facing forensic probe: WO-006R28.
- Latest mesh-source forensic diagnostic: WO-006R30.
- Current CFD status: `pressure_sanity_passed_route_smoke_pending`.
- Passed release gates: `TOOLCHAIN_PASS`, `PRESSURE_SANITY_PASS`.
- Next required release gate: `ROUTE_SMOKE_PASS` for canonical half-wing
  hybrid BL viscous route-smoke.
- Phase 3 route-smoke gate exists, but `ROUTE_SMOKE_PASS` has not passed. The
  current Gmsh topological BL extrusion attempt is rejected evidence, not an
  active success path.
- R-series forensic blockers that retired the old route:
  - `su2_dual_orthogonality_angle_extreme`
  - `su2_dual_cv_face_area_aspect_ratio_extreme`
  - `su2_dual_cv_sub_volume_ratio_extreme`
  - `route_smoke_cd_implausibly_high_for_hpa_main_wing`
  - `coarse_medium_fine_solver_ladder_not_run`
- Engineering read: R27 cleared marker ownership, but R28 showed the repaired
  mesh is not CFD usable yet.  SU2 can read the mesh/markers, but solver-side
  dual-control-volume quality is pathological; medium/fine ladder runs are
  blocked until the BL/core transition sizing and dual-volume quality are
  repaired.  R29 did not find a primal adjacent-tet volume jump large enough to
  explain the SU2 dual-volume metric; R30 then reproduced the R28
  `2.07841e11` CV sub-volume ratio with a SU2-style vertex subvolume scan and
  localized the worst point to the `farfield` marker / `core_tet_mesh` region.
  That evidence now retires the custom all-tet/global-star/owner-pyramid route
  from active CFD delivery.  Do not open R31/R32/R33 to local-patch this mesh;
  rebuild through the canonical half-wing hybrid route and only advance named
  manifest gates.  The canonical pressure-only half-wing case now passes, so the
  next risk is the hybrid BL route-smoke, not another pressure/marker repair.
  The first canonical Gmsh-extruded hybrid attempt preserved prism/tet cell
  types, but `INC_RANS/SA` still diverged and SU2 reported max CV sub-volume
  ratio around `1.81024e8`; one-iteration force breakdown localized the bad
  drag to the primary wing wall markers rather than `tip_wall`, `te_wall`, or
  `closure_wall`.  This points away from closure-force cleanup and toward an
  owned near-wall topology / direct hybrid handoff.  The direct surface-prism
  writer now carries its own pre-solver quality gate; the default wall-resolved
  first height creates root-symmetry sidewall quads with aspect ratio around
  `7794.66`, so the direct topology is blocked before another SU2 numerics run.
  A partial-BL probe now shows that extruding prism layers only on
  `wing_upper` / `wing_lower` can pass the direct prism quality gate; the
  partial-BL sidewall quads are now assigned back to `tip_wall`, `te_wall`,
  and `closure_wall`.  The remaining named blocker is explicit conformal
  original cap-face materialization before tetra-core merge.  A small
  cap-materialized core probe confirms that this topology can produce a
  pure-tetra core when the inner boundary is triangulated.

## Problems And Repairs

| Problem | Symptom / bad evidence | Root cause found | Working repair / current method | Remaining gate |
|---|---|---|---|---|
| no-BL or wrong wall setup being mistaken for CFD | finite CL/CD existed, but prior no-BL / poor BL cases produced `CD≈0.4-0.6`, far above expected HPA main-wing `0.0XX` drag order | solver could produce finite numbers on invalid near-wall physics | WO-006R8 basic NACA4412 BL sanity: Gmsh BL quads + SU2 `INC_RANS/SA` + no-slip `MARKER_HEATFLUX` gave `CL=0.8876`, `CD=0.02168`; WO-006I gates reject no-BL completion | Phase 1 must add current root and current mid-or-tip 2D wall-resolved sanity before any 3D route-smoke |
| direct stageback route PLC failure | Gmsh `PLC Error` / segment-facet intersection on no-BL-hole stageback attempts | direct stageback topology collides with current GO transition/tip geometry | Treat stageback route as historical diagnostic once core/mixed handoff artifacts exist | Do not revive direct stageback as active delivery; rebuild under `canonical_hybrid_halfwing_v0` if a named gate needs pressure/geometry isolation |
| R13 core mesh was not enough for mixed handoff | core/farfield mesh could pass marker/quality alone, but BL/core interface was not conformal | core surface and near-wall candidate had incompatible boundary triangulation/ownership | R14-R20 localized residuals; R19 loop-cap owner pyramids and R20 left-tip star cells provided local repair bases | Superseded by R22/R24/R27 path; keep as provenance |
| local split choices created internal nonconformality | R21 found `7960` internal split leaks and `64` nonmanifold split faces | per-cell local best split does not guarantee global cell-to-cell conformality | R22 global center-star split with deterministic internal face treatment | Superseded by R24/R27 path |
| degenerate global-star triangles | R22 had `128` zero-area star triangles | all degenerate triangles were empty-marker wake-receiver zero-area faces | R23 localized them to `32` wake_receiver cells; R24 proved they can be culled without losing owned markers | Done for R27 handoff basis |
| R25 mixed SU2 handoff had unmarked exterior faces | R25 wrote `332,221` tets with volume quality pass, but marker audit failed: `68` unmarked exterior faces, area `0.075898249 m^2` | loop-cap / wake-edge closure faces existed as exterior volume faces without final SU2 marker ownership | R26 classified all `68` faces: `60` loop-cap owner pyramid exterior, `4` physical-wall-edge closure, `2` candidate wake-edge, `2` core wake-edge; no unclassified faces | R27 applied the repair |
| R26 repair plan not applied yet | WO-006I preflight saw `near_wall_mixed_su2_boundary_marker_repair_not_applied` | R26 only created a repair plan; R25 writer still emitted the old marker set | R27 applies only R26 records with `recommended_marker=wing_wall` and rewrites the mixed SU2 handoff | Done: R27 marker audit pass |
| old blocked artifacts overriding newer pass artifacts | WO-006I saw R27 pass artifact but still reported R26/R25 blocker | artifact aggregation overwrote a newer pass with older blocked records | make mixed handoff readiness cumulative and preserve the first/ready handoff record | Done in WO-006I gate tests |
| solver-side dual-volume quality is pathological | R28 FDS/MUSCL route-smoke diverged at iteration `5`; SU2 log reports min orthogonality angle `0.00108069 deg`, max CV face-area aspect ratio `5.15199e8`, and max CV sub-volume ratio `2.07841e11` | R27 only checked positive primal tetra volume / marker ownership; it did not control SU2 dual-control-volume quality | R28 parser remains useful as a future route-smoke gate | Do not repair the R27 mesh as active delivery; use this as rejection evidence for all-tet BL handoff |
| primal source-pair volume jump is not enough to explain R28 | R29 rebuilt the R25/R27 source-provenance mixed mesh and found `1,432` internal faces with adjacent tet volume ratio `>=1000`, but the maximum ratio was only `29263.77`; worst source pair was `culled_global_star_near_wall|culled_global_star_near_wall` | The SU2 max CV sub-volume ratio `2.07841e11` is not reproduced by this simple shared-face primal volume-jump proxy | R29 records the negative result in `summary.json`, `internal_face_volume_jump_records.csv`, and `dual_quality_source_localization_report.md` | Treat as forensic evidence that simple primal quality gates are insufficient; new route must require SU2 dual-control-volume quality |
| SU2-style vertex subvolume hotspot is now localized | R30 reproduces the R28 max CV sub-volume ratio: `207840927876.89658` vs R28 `2.07841e11`; worst point `56784` is at `(-2.684534382258478, 21.21191727545568, 1.867804964000869)` with `point_markers=["farfield"]` and incident source counts `{"core_tet_mesh": 1704}` | The main dual-volume blow-up is generated by core/farfield tetra construction around the tip/farfield region, not by a missing marker or by whole-tet adjacent volume ratio alone | R30 writes `summary.json`, `dual_subvolume_hotspots.csv`, and `dual_subvolume_localization_report.md` using a SU2-style vertex subvolume max/min scan | Forensic-only. This closes the old route as active delivery; new work starts from hybrid half-wing topology, not R30 local patching |
| conservative numerics can run but do not make the mesh credible | R28 JST, `MUSCL_FLOW=NO`, `CFL=0.02` completed `180` iterations but ended at `CL=0.6908`, `CD=0.3916`, `Cm=-0.1424`; last-100 force and residual stability both failed | Lower-order numerics can avoid immediate divergence, but high drag and unstable forces persist on the same pathological dual mesh | Use conservative numerics only as diagnostic evidence; do not treat finite coefficients as route success | Canonical route-smoke must pass on the hybrid half-wing route; conservative numerics alone can never set `ROUTE_SMOKE_PASS` |
| current root 2D sanity failed on closed TE BL mesh | First Phase 1 root DAE31 run diverged at iteration `18` with `CD=1.799858027e21`; Gmsh mesh had one negative-quality BL quad near the closed/cusped trailing edge | The DAE31 DAT is closed at the TE, unlike the finite-gap NACA/tip cases; Gmsh boundary-layer extrusion around the cusp collapsed a quad | `load_dat_airfoil_loop()` now regularizes duplicate closed TE points into a `0.002c` finite TE cap for the 2D sanity mesh and records loop diagnostics | Done for Phase 1 only. This is a toolchain-sanity mesh regularization, not a claim that the 3D wing TE/cap is solved |
| half-wing pressure mesh initially diverged on over-clustered tip cap | Phase 2 first 3D Euler/slip run with `points_per_side=12`, `spanwise_subdivisions=1` diverged by iteration `10`; SU2 dual quality was much better than R28 but still had max CV sub-volume ratio `3.08571e6` and pressure coefficients blew up | Coarse pressure surface had high aspect-ratio wing/tip-cap panels from excessive chordwise cosine clustering at the small tip chord; worst Gmsh elements localized near the tip cap, not the old farfield pole | Canonical Phase 2 pressure mesh now uses `points_per_side=6`, `spanwise_subdivisions=4`, preserving marker split while avoiding over-clustered tip-cap chordwise points. SU2 dual gate is now parsed from solver logs and required by the release gate | Done for Phase 2 only. This is a pressure-only mesh recipe, not the viscous BL prism/hexa route |
| first canonical Gmsh-extruded hybrid BL route-smoke fails | Default Phase 3 mesh has hybrid cell types (`15,600` prism BL cells and `2,857` core tets), but SU2 `INC_RANS/SA` diverges and reports max CV sub-volume ratio about `1.81024e8`; pps12/s6 diagnostics reduce some viscous drag with relaxed first height but pressure CD remains high | Gmsh topological BL extrusion over the faceted half-wing surface does not produce a solver-credible vertex-centered dual-control-volume mesh for the viscous route | Phase 3 gate now rejects `1e8`-scale dual sub-volume ratio and keeps closure/tip/TE forces separate; one-iteration force breakdown shows closure/tip/TE CD are not the dominant source | Replace this path with mesh-native owned BL topology / direct hybrid SU2 handoff; do not spend the next task on CFL, Green-Gauss, laminar, or closure-marker tuning |
| direct surface-prism handoff has root sidewall distortion | Direct writer can preserve prism BL + tetra core and oriented markers, but SU2 reports distorted prism/quad elements and Euler/slip diverges at iter 10 with initial `CD≈0.2613` | wall-resolved first height `5e-5 m` is being carried onto long root-symmetry sidewall quads; the default 24-layer probe has root-side quad aspect ratio about `7794.66` and `90` root-side quads above `1000` | `direct_prism_quality_gate` now reports prism signed volume and root-symmetry quad aspect ratio before solver launch | Fix root/TE/cap policy or partial-BL root handling before rerunning route-smoke; do not use CFL/limiter changes as pass evidence |
| partial wing-only prism BL needs explicit caps | `wing_upper` / `wing_lower` only prism extrusion at `points_per_side=42`, 24 layers, growth `1.2` gives `124,416` prism cells with non-positive signed volume `0` and root-sidewall max aspect `966.04`; sidewall quads are assigned to `tip_wall=1944`, `te_wall=1344`, and `closure_wall=192` | The primary wing BL and sidewall marker ownership can be made locally clean, but original cap faces still need to be materialized between wall and BL outer interface before the tetra core sees a watertight inner boundary | `write_phase3_partial_wing_prism_handoff_su2()` writes a caps-pending artifact and blocks `core_tetra_interface` with `blocked_until_caps_materialized` / `blocked_cap_faces_missing` | Materialize conformal caps for `tip_wall=82`, `te_wall=28`, and `closure_wall=4` source faces, then retry tetra-core merge |
| cap-materialized core probe needs scale-up | pps12/l4 probe builds an inner boundary from BL outer interface, cap sidewall quads, and original cap faces; Gmsh fills it with `7,295` tetra and no forbidden core element types | Triangulating the discrete inner boundary avoids Gmsh pyramid insertion on cap-sidewall quads | `run_phase3_partial_wing_cap_core_probe()` writes `partial_wing_cap_core_probe_report.json` and `core.msh` for small topology proof | Scale to pps42/l24, then merge prism BL + core tets into SU2 with internal interface faces removed |

## Phase 1 Toolchain Sanity Evidence

- Script: `scripts/run_canonical_hybrid_phase1_toolchain_sanity.py`
- Artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/toolchain_sanity/`
- Manifest status: `TOOLCHAIN_PASS`
- Current next manifest gate after Phase 2: `ROUTE_SMOKE_PASS`
- Case results:
  - `naca4412_2d`: completed, `CD=0.02075585229`, last-100
    `CL/CD` relative spans `4.56e-5` / `4.77e-4`
  - `current_root_dae31`: completed, `CD=0.02117848483`, last-100
    `CL/CD` relative spans `2.29e-4` / `1.65e-3`
  - `current_tip_cst`: completed, `CD=0.02047500345`, last-100
    `CL/CD` relative spans `8.30e-6` / `4.83e-4`
- Engineering read: this clears solver / no-slip / BL / force-window sanity for
  the small 2D cases. It does not clear 3D geometry, marker, closure, farfield,
  dual-volume, y+ postprocess, pressure-only, route-smoke, or grid-ladder risk.
- Root-section note: the first DAE31 attempt failed because the closed/cusped TE
  produced a negative-quality Gmsh BL quad. The Phase 1 2D mesh now regularizes
  duplicate closed TE points to a `0.002c` finite TE cap and records loop
  diagnostics; this is not a 3D wing TE/cap sign-off.

## Phase 2 Pressure Sanity Evidence

- Script: `scripts/run_canonical_hybrid_phase2_pressure_sanity.py`
- Tests: `tests/test_canonical_hybrid_phase2_pressure_sanity.py`
- Artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/pressure_sanity/`
- Manifest status: `PRESSURE_SANITY_PASS`
- Next manifest gate: `ROUTE_SMOKE_PASS`
- Setup:
  - half-wing domain with `root_symmetry`
  - `SOLVER=INC_EULER`
  - `AOA=0`
  - `INC_NONDIM=INITIAL_VALUES`
  - `MARKER_EULER=(wing_upper, wing_lower, tip_wall, te_wall, closure_wall)`
  - `MARKER_MONITORING=(wing_upper, wing_lower)`
- Mesh / marker evidence:
  - volume elements: `2,974` tetra
  - marker audit: pass
  - markers: `wing_upper`, `wing_lower`, `tip_wall`, `te_wall`,
    `closure_wall`, `root_symmetry`, `farfield`
  - max farfield vertex incident volume cells: `4`
  - min Gmsh volume quality: `0.004642472`
  - SU2 dual quality: min orthogonality `19.4086 deg`, max CV face-area
    aspect ratio `7487.37`, max CV sub-volume ratio `186725`
- Solver / force evidence:
  - solver completed at iteration `383`
  - final `CL=0.3653440743`, `CD=0.01778726857`, `CMy=-0.07066749827`
  - last-100 `CL/CD` relative spans: `0.00445098` / `0.00552810`
  - force breakdown surfaces: `wing_upper`, `wing_lower`
  - geometry marker areas are recorded separately for `tip_wall`, `te_wall`,
    and `closure_wall`; they are not silently merged into a single `wing_wall`
- Engineering read: this clears the pressure/geometry/marker/reference sanity
  split that was missing before BL work. It does not clear viscous drag, BL
  prism/hexa quality, y+, transition, closure force contribution in viscous
  flow, or coarse/medium/fine ladder convergence.

## Phase 3 Route-Smoke Gate Evidence

- Script: `scripts/run_canonical_hybrid_phase3_route_smoke.py`
- Tests: `tests/test_canonical_hybrid_phase3_route_smoke.py`
- Manifest status: still pending; `ROUTE_SMOKE_PASS` is **not** in
  `passed_gate_statuses`.
- Current failed artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/route_smoke/`
- Default mesh evidence:
  - volume element types: `{'4': 2857, '6': 15600}`
  - BL cell count: `15600`
  - mesh-quality gate: pass on positive volume; minSICN is treated as a warning
    because stretched prism BL elements must be judged by solver-side dual
    quality before CFD acceptance.
  - marker split: `wing_upper`, `wing_lower`, `tip_wall`, `te_wall`,
    `closure_wall`, `root_symmetry`, `farfield`
- Solver evidence:
  - setup: `INC_RANS`, `SA`, no-slip `MARKER_HEATFLUX`, `AOA=0`,
    `INC_NONDIM=INITIAL_VALUES`
  - run status: failed by divergence
  - SU2 dual quality in failed default case: min orthogonality `22.1539 deg`,
    max CV face-area aspect ratio `51630.3`, max CV sub-volume ratio
    `1.81024e8`
- Diagnostic force split:
  - pps12/s6 one-iteration case: primary `wing_upper + wing_lower`
    `CD≈0.4417`; `tip_wall≈5.6e-05`, `te_wall≈0.001204`,
    `closure_wall≈0.000112`
  - pps12/s6 relaxed first height one-iteration case: primary `CD≈0.3049`;
    pressure `CD≈0.2596`, viscous `CD≈0.0453`
- Engineering read: preserving prism/tet element types is necessary but not
  sufficient. The closure/tip/TE markers are not currently the dominant drag
  pollution source; the primary wall / BL topology and SU2 dual control volume
  remain the blocker. Low-CFL, AOA=-4, laminar, and Green-Gauss diagnostics did
  not convert this path into an acceptable route-smoke. The next implementation
  should move to mesh-native owned BL topology and a direct hybrid SU2 handoff,
  not another local patch on the Gmsh-extruded path.

## R27 Forensic Evidence

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

## R28 Forensic Evidence

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

## R29 Forensic Evidence

- Script: `scripts/probe_wo006r29_dual_quality_source_localization.py`
- Tests: `tests/test_wo006r29_dual_quality_source_localization_probe.py`
- Artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r29_dual_quality_source_localization_probe/`
- Diagnostic scope: source-aware internal shared-face adjacent tet volume
  ratios on the R25/R27 mixed mesh; no SU2 solve, no y+ postprocessing, no CFD
  coefficient evidence.
- Nodes / volume elements: `56,873` / `332,221`
- Source counts:
  - `culled_global_star_near_wall=322,432`
  - `core_tet_mesh=9,669`
  - `loop_cap_owner_pyramid_tet_split=120`
- Internal faces recorded with volume ratio `>=1000`: `1,432`
- Maximum internal-face volume ratio: `29263.77`
- Worst source pair: `culled_global_star_near_wall|culled_global_star_near_wall`
- Highest `core_tet_mesh|culled_global_star_near_wall` ratio: `14309.05`
- Engineering read: this is a useful negative result.  It does not clear the
  R28 SU2 dual-quality blocker; it only says the blocker is not explained by a
  simple primal shared-face adjacent tet volume ratio above `1e6`.

## R30 Forensic Evidence

- Script: `scripts/probe_wo006r30_su2_dual_subvolume_localization.py`
- Tests: `tests/test_wo006r30_su2_dual_subvolume_localization_probe.py`
- Artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r30_su2_dual_subvolume_localization_probe/`
- Diagnostic scope: SU2-style vertex dual-control-volume sub-element max/min
  volume ratio, based on SU2 `CPhysicalGeometry::ComputeMeshQualityStatistics`.
  No SU2 solve, no y+ postprocessing, no CFD coefficient evidence.
- Nodes / volume elements: `56,873` / `332,221`
- Positive subvolume samples: `3,986,652`; non-positive subvolumes: `0`
- Hotspot records above ratio `1e6`: `90`
- Maximum SU2-style CV sub-volume ratio: `207840927876.89658`
- R28 solver-log max CV sub-volume ratio: `2.07841e11`
- Worst point:
  - point index `56784`
  - xyz `(-2.684534382258478, 21.21191727545568, 1.867804964000869)`
  - point markers: `["farfield"]`
  - incident element source counts: `{"core_tet_mesh": 1704}`
  - source pair: `core_tet_mesh|core_tet_mesh`
- Second worst point:
  - point index `56503`
  - xyz `(-2.684534382258478, -21.0477871116104, 0.6871641871325508)`
  - point markers: `["farfield"]`
  - incident element source counts: `{"core_tet_mesh": 1778}`
- Engineering read: this is the first localization that matches the R28 SU2
  metric magnitude.  It moves the primary repair target to the core/farfield
  tetra construction near the tip/farfield boundary; the R27 mesh remains
  unusable for medium/fine ladder until this dual-volume hotspot is repaired.

## Known Unknowns

- Whether repairing BL/core transition sizing is sufficient, or whether the
  loop-cap / wake closure topology must also be reshaped.
- Whether solver-postprocessed y+ remains acceptable across the full wing,
  especially tip/wake/loop-cap closure regions.
- Whether the pressure-only `CD=0.0178` remains compatible with the first
  viscous route-smoke once no-slip BL and friction are added.

## Next Repair / Run Order

1. Phase 1 `TOOLCHAIN_PASS`: done.  Three 2D wall-resolved RANS/SA sanity cases
   completed with `CD≈0.0205-0.0212` and stable force windows.  Do not read this
   as 3D CFD completion evidence.
2. Phase 2 `PRESSURE_SANITY_PASS`: done.  Half-wing Euler/slip pressure sanity
   passed with `CD=0.0177873`, stable last-100 force window, marker split, and
   SU2 dual-control-volume quality gate.
3. Phase 3 route build: create `canonical_hybrid_halfwing_v0` geometry and mesh
   with prism/hexa BL, tetra core, conformal interface, root symmetry, and
   separate `wing_upper`, `wing_lower`, `tip_wall`, `te_wall`, `closure_wall`,
   `root_symmetry`, `farfield` markers.  Preserve hybrid cell types in SU2.
4. Phase 4 `ROUTE_SMOKE_PASS`: first viscous 3D smoke uses geometry incidence
   with `AOA=0`, half-wing `REF_AREA`, `INC_RANS/SA`, no-slip walls,
   `INC_NONDIM=INITIAL_VALUES`, SU2 dual-quality gate, finite CL/CD/Cm, last-100
   or last-200 force stability, `CD <= 0.15`, and explicit pressure/viscous/
   closure force breakdown.  Conservative numerics may diagnose but cannot pass.
5. Phase 5 `GRID_LADDER_PASS`: only after route-smoke passes, run coarse /
   medium / fine with the same generator, geometry, marker policy, solver config,
   and force markers.  Any rung that needs special-case repair fails the route.
