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
- Current collar/core blocker question packet:
  `docs/reports/wo006_cfd_collar_core_blocker_gpt_pro_prompt.md`.
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
  pure-tetra core when the inner boundary is triangulated.  GPT Pro follow-up
  review then narrowed the real partial-BL blocker further: non-root prism rim
  quads cannot conformally hand off directly to tetra core; they require an
  explicit prism-to-pyramid-to-tet transition collar.  A minimal artificial
  transition unit proves that contract, and the real-wing pps42/l24 handoff now
  converts those rim quads into internal pyramid bases without leaking them into
  force-wall markers.  A small collar+cap core probe then shows the resulting
  triangular transition interface plus original cap faces can tetra-fill without
  forbidden core element types at pps12/l4 scale.  pps24/l4 scale-up shows collar
  thickness is now a real geometry constraint: `2.5e-4 m` still self-intersects,
  while `1.0e-4 m` tetra-fills cleanly.  Thin-collar pps42 scale probes then
  tetra-fill at l4/l8/l16, but l16 already costs about six minutes on this Mac,
  so runtime is now part of the gate.  The first merged SU2 hybrid writer can
  now write a pps12/l4 prism+pyramid+tet mesh with clean markers and no unused
  nodes, but SU2 pressure-only smoke exposes a new dual-volume pathology in the
  collar/core interface.  The GPT Pro suggested pps42/layers=3 Build 1 was also
  probed and still fails the pre-solver dual gate, so the current blocker is not
  simply too many BL layers.  The current dual proxy now reports incident
  element geometry at each hotspot; pps42/l3 shows the worst vertex couples
  `6e-5 m` collar/core local edges to meter-scale core edges.  The proxy now
  gates this directly with `max_hotspot_incident_edge_length_ratio=1000`.  A
  new segmented-collar artificial unit shows the next topology recipe: split the
  long prism rim into short segments before pyramid collar handoff.

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
| cap-materialized core probe is only a topology proof | pps12/l4 probe builds an inner boundary from BL outer interface, cap sidewall quads, and original cap faces; Gmsh fills it with `7,295` tetra and no forbidden core element types | Triangulating the discrete inner boundary avoids Gmsh pyramid insertion on cap-sidewall quads, but this alone does not define the partial-BL rim transition | `run_phase3_partial_wing_cap_core_probe()` writes `partial_wing_cap_core_probe_report.json` and `core.msh` for small topology proof | Do not scale this directly to pps42/l24 as if cap triangulation solved the rim handoff; first enforce the prism-to-pyramid-to-tet transition-collar contract |
| partial-BL rim needs pyramid transition collar | GPT Pro follow-up pointed out that tetra cannot conformally attach to exposed prism side quads; without an explicit collar Codex will keep repairing Gmsh cap loops instead of defining mesh topology | Partial BL only on `wing_upper` / `wing_lower` leaves non-root prism rim quads at TE/tip/closure; those must be internal transition faces, not wall force markers and not direct tetra contacts | `write_phase3_minimal_transition_unit_su2()` proves the artificial contract; `write_phase3_partial_wing_transition_collar_handoff_su2()` applies it to real wing pps42/l24 with `124,416` prisms + `3,480` pyramids, converting `tip_wall=1944`, `te_wall=1344`, `closure_wall=192` rim quads into internal pyramid bases, `transition_collar_interface=13,920` triangles, `force_wall_rim_marker_leak_count=0`, positive pyramid volumes, and SU2 ownership pass | Materialize original tip/TE/closure physical cap faces and merge tetra core into the same hybrid SU2 mesh; then require pressure-only CD sanity before any RANS route-smoke |
| collar+cap shell can tetra-fill at small scale | pps12/l4 collar+cap probe combines `bl_outer_interface`, `transition_collar_interface`, and original cap faces; Gmsh fills the core with `9,088` tetra and no forbidden core element types | The explicit collar makes the prism rim compatible with a triangular tetra-core boundary at small scale | `run_phase3_partial_wing_transition_collar_core_probe()` writes `partial_wing_transition_collar_core_probe_report.json` and `core.msh` | Scale the collar+cap core merge to pps42/l24 and then write the merged SU2 hybrid mesh with internal interface markers removed |
| collar height controls pps24 scale-up | pps24/l4 with `collar_height=2.5e-4 m` still fails Gmsh core fill with `PLC Error: A segment and a facet intersect at point`; `collar_height=1.0e-4 m` fills with `12,028` tetra and no forbidden core element types | The transition collar can solve element compatibility but still self-intersects if apex offset is too thick for local TE/tip/cap geometry | Regression test `test_partial_wing_transition_collar_core_probe_scales_to_pps24_with_thin_collar` locks the thin-collar pass | Use thin collar policy for the next pps42 and layer ladder; do not interpret thick-collar PLC failure as solver/numerics issue |
| thin-collar pps42 core scale reaches 16 layers | pps42/l4 fills with `16,462` tetra in about `51 s`; pps42/l8 fills with `20,093` tetra in about `118 s`; pps42/l16 fills with `26,600` tetra in about `355 s`; all have forbidden core element counts `{}` | The collar+cap topology is not blocked by full chordwise resolution up to 16 layers, but Gmsh runtime grows quickly | Manual artifacts under `partial_wing_transition_collar_core_probe_pps42_l4_h1e-4/`, `_l8_h1e-4/`, and `_l16_h1e-4/` record the runs | Do not blindly run l24 as the next proof; write merged SU2 hybrid mesh and run marker/dual-quality/pressure sanity on l4 or l8 first |
| first merged collar-core SU2 writer passes marker/readability gates | pps12/l4 merged writer outputs `5,376` prisms + `340` pyramids + `8,690` tetra; final markers are `wing_upper`, `wing_lower`, `tip_wall`, `te_wall`, `closure_wall`, `root_symmetry`, `farfield`; internal `bl_outer_interface` / `transition_collar_interface` are removed | The final SU2 writer must compact unused prism-layer nodes; otherwise SU2 aborts with `NPOIN` mismatch even though parser/ownership audits pass | `write_phase3_partial_wing_transition_collar_core_hybrid_su2()` now compacts unused nodes (`4` removed in pps12/l4), marker audit / ownership pass | Run pressure-only sanity before any RANS; do not treat writer success as route-smoke |
| merged collar-core pressure smoke exposes new dual pathology | pps12/l4 pressure-only probe reads mesh but fails after `3` rows / iteration `2`; dual metrics are min orthogonality `0.0105006 deg`, max CV face-area aspect ratio `7.58862e9`, max CV sub-volume ratio `4.37135e11`; pps42/layers=3 also has max proxy about `3.39398e11`; forces breakdown missing | The pyramid collar / local core interface creates vertex-dual scale jumps even though topology and marker ownership are now valid.  In pps42/l3 the worst point has incident core min edge `6e-5 m`, max core edge about `1.68 m`, and incident core edge ratio `~1.37e4`; the route proxy now also blocks hotspot edge ratio above `1000` | Artifacts `partial_wing_transition_collar_core_hybrid_pps12_l4_pressure_probe/pressure_probe_report.json` and `partial_wing_transition_collar_core_hybrid_pps42_l3/partial_wing_transition_collar_core_hybrid_report.json` record the failure | Fix collar/core-interface quality before RANS; likely need local termination ramp / structured transition patch or a mature layer-addition mesher, not just BL layer-count reduction |
| segmented collar scale-transition unit passes | Artificial unit writes `32` prisms + `16` pyramids + `96` tetra, with `16` short rim segments, rim quad max edge ratio about `500`, `tet_to_prism_quad_contact=0`, `non_root_exposed_prism_quad_count=0`, and dual proxy pass | The scale-jump blocker can be avoided when long prism rim quads are segmented before pyramid collar handoff; this is the first topology evidence for a local structured/ramped transition patch | `write_phase3_segmented_collar_scale_transition_unit_su2()` writes `segmented_collar_scale_transition_unit/mesh.su2` and `.report.json` | Apply the segmentation/ramp rule to real-wing TE/tip/closure rims, then rerun pps42 layers 3/8/16/24 pre-solver gates before pressure/RANS |
| pps42/l24 real-wing rim segmentation is now quantified | Existing single-pyramid handoff converts `3,480` rim quads, but max single-base edge ratio is about `1.64e4`; keeping each segmented base below edge-ratio `1000` requires about `6,928` layer-expanded rim pieces: `te_wall=4,376`, `tip_wall=1,944`, `closure_wall=608`; per-quad split plan predicts max post-split base edge ratio about `997.8`; source-edge collapse gives `145` source rim edges and about `809` required segments | The next real-wing implementation should split only the long source-rim direction before pyramid collar creation, not globally refine the whole core | `partial_wing_transition_collar_handoff_pps42_l24/partial_wing_transition_collar_handoff_report.json` now records `segmented_collar_requirement` with per-quad and source-edge split plans | Implement segmented/ramped real-wing collar and re-run dual proxy before pressure/RANS |
| segmented pps42/l3 source-rim handoff passes collar-base gate | `segmented_partial_wing_transition_collar_handoff_pps42_l3/` splits `64` long source rim edges into `728` segments before BL extrusion, adds `664` source vertices, and writes `17,544` prisms + `2,427` pyramids; after splitting, max single pyramid base edge ratio is about `982.03`, `max_required_segments_per_quad=1`, force-wall rim leak is `0`, pyramid non-positive count is `0`, and SU2 boundary ownership passes | The actionable implementation is source-edge splitting before prism extrusion, not post-hoc splitting of every layer-expanded rim quad; tip source edges are already below the split threshold in this gate | `write_phase3_segmented_partial_wing_transition_collar_handoff_su2()` writes the segmented caps-pending handoff and reports `source_rim_edge_split_plan` / `segmented_surface` | Use this segmented surface for the next pps42/l3 core merge and dual proxy; do not run pressure/RANS until core merge and dual-quality pass |
| segmented pps42/l3 core merge still fails dual-quality gate | `segmented_partial_wing_transition_collar_core_hybrid_pps42_l3/` writes `17,544` prisms + `2,427` pyramids + `36,327` tetra in about `179 s`; required markers are present and SU2 boundary ownership passes, but dual proxy fails with max CV sub-volume ratio about `1.6899e11` and max hotspot incident edge ratio about `2.2339e4` | Source-rim segmentation fixed the collar base edge-ratio problem, but Gmsh still places collar-adjacent core tets so a TE/upper hotspot sees `5e-5 m` BL/collar edges and about `0.82 m` core edges at the same vertex | `write_phase3_segmented_partial_wing_transition_collar_core_hybrid_su2()` writes the merged segmented mesh and records `dual_subvolume_proxy` in the pps42/l3 artifact | Next repair must be collar-adjacent core grading: local sizing field, structured transition patch, or multi-row transition collar; do not run pressure/RANS |
| collar boundary-point sizing is rejected | pps12/l4 with `transition_collar_interface` boundary points set to `0.05 m` mesh size generated `35,095` core tetra in about `110 s`, but dual proxy worsened to max CV sub-volume ratio about `1.1247e16` and max hotspot incident edge ratio about `1.072e5` | Forcing small sizes on interface points does not create a controlled growth layer; it can make local core topology more pathological while still leaving larger core edges incident to the same vertices | `segmented_partial_wing_transition_collar_core_hybrid_pps12_l4_pointsize005/segmented_partial_wing_transition_collar_core_hybrid_report.json` records the rejected probe; `_core_boundary_point_size_targets()` remains a diagnostic helper, not an active route policy | Do not use point-size hacks as success criteria; move to explicit multi-row / structured transition patch |
| structured transition patch unit passes with sidewall closure | Artificial unit writes `4` segmented collar bases, `4` primary pyramid collars, `40` prisms, `106` pyramids, and `432` tetra; transition rows grow `0.03 m -> 0.09 m` with max row growth ratio `3.0`; `102` transition-prism sidewall quads are converted into sidewall pyramid + tetra triangular interface; dual proxy reports pass and no hotspot edge-ratio blocker | Controlled growth separates BL/collar vertices from larger core tetra vertices, and explicit sidewall closure prevents exposed prism quads without using force-wall markers | `write_phase3_structured_transition_patch_unit_su2()` writes `structured_transition_patch_unit/mesh.su2` and `.report.json`; status is `structured_transition_patch_unit_pass` | Apply this sidewall-closure / triangular-interface rule to the real-wing segmented pps42/l3 collar and rerun dual proxy; do not run pressure/RANS until real-wing core merge passes |
| bounded real-wing structured transition handoff passes | Tiny real-wing handoff uses `points_per_side=4`, `spanwise_subdivisions=1`, `first_layer_height=1e-3 m`, and `layers=1`; it writes `482` prisms, `1175` pyramids, and `4512` tetra; `188` collar interface triangles feed two transition rows; `1128` sidewall closure pyramids and `4512` sidewall closure tets close exposed prism quads; ownership, topology, and dual proxy pass | The structured sidewall-closure contract can be projected onto the real-wing segmented-collar data model, but this is deliberately not a y+ or pps42/l3 proof | `write_phase3_segmented_partial_wing_structured_transition_handoff_su2()` writes `segmented_partial_wing_structured_transition_handoff_tiny/mesh.su2` and `.report.json`; final markers replace `transition_collar_interface` with `transition_collar_outer_interface` | Next step is an element-count-controlled pps42/l3 projection or shared-node sidewall sewing; do not run pressure/RANS from the tiny topology smoke |
| pps42/l3 structured transition projection is blocked by element count | Projection-only preflight for pps42/l3 has `9708` collar interface triangles; current per-triangle closure rule would create `19,416` transition prisms, `58,248` sidewall closure pyramids, and `232,992` sidewall closure tetra; projected final count is `36,960` prisms, `60,675` pyramids, `232,992` tetra, total `330,627` volume elements, exceeding the `250,000` Mac-safe projection gate | The tiny handoff topology is valid but its naive per-interface-triangle sidewall closure is not scalable enough for the current pps42/l3 Mac-safe route | `plan_phase3_segmented_partial_wing_structured_transition_handoff()` writes/feeds the projection report under `segmented_partial_wing_structured_transition_projection_pps42_l3/structured_transition_projection_report.json`; status is `segmented_partial_wing_structured_transition_projection_blocked` | Do not generate the naive full pps42/l3 structured handoff. Next topology should share/stitch adjacent transition sidewalls, coarsen the collar band, or apply transition only on true outer rim edges before retrying dual gate |
| pps42/l3 stitched-sheet structured projection is Mac-safe | Same pps42/l3 collar has `9708` interface triangles, `15374` interface edges, `1624` boundary edges, and `0` nonmanifold edges; with shared-node stitched transition rows, projected closure drops to `3248` sidewall closure pyramids and `12992` closure tetra; projected total is `36,960` prisms, `5675` pyramids, `12,992` tetra, total `55,627` volume elements, below the `250,000` gate | Adjacent transition prisms must share row nodes so internal sidewall quads pair; only boundary edges should be closed. This is the first scalable pps42/l3 structured-transition policy | `plan_phase3_segmented_partial_wing_structured_transition_handoff(..., sidewall_closure_policy="stitched_sheet")` writes/feeds `segmented_partial_wing_structured_transition_projection_pps42_l3_stitched/structured_transition_projection_report.json`; status is `segmented_partial_wing_structured_transition_projection_ready` | Implement shared-node stitched transition sheet next, then rerun topology, element-quality, ownership, and dual gates before any pressure/RANS |
| pps42/l3 stitched-sheet structured handoff passes pre-core gates | Shared-node stitched writer now creates one row-node sheet per interface vertex and closes only exposed boundary-edge sidewalls. The active pps42/l3 artifact uses transition rows `0.01 m -> 0.03 m`; the earlier `0.03 m -> 0.09 m` row choice generated a structured-transition prism dual hotspot with max CV sub-volume ratio about `3.36e8`. The accepted artifact writes `36,960` prisms + `5,987` pyramids + `14,240` tetra, total `57,187` volume elements; topology has no unmarked boundary faces, nonmanifold faces, direct tet-to-prism-quad contact, exposed non-root prism quads, or exposed pyramid faces; element quality, SU2 boundary ownership, and dual proxy all pass | GPT Pro's partial-BL rim diagnosis is confirmed: the missing topology was shared-node prism-row stitching plus bounded row growth, not another Gmsh cap patch. Row-height scale matters; too-large transition rows reintroduce SU2 dual-volume pathology even with valid topology | `write_phase3_segmented_partial_wing_structured_transition_handoff_su2(..., sidewall_closure_policy="stitched_sheet", transition_row_heights_m=(0.01, 0.03))` writes `segmented_partial_wing_structured_transition_handoff_pps42_l3_stitched_r010_030/mesh.su2` and `.report.json`; regression test `test_segmented_partial_wing_stitched_transition_handoff_pps42_l3_passes_dual_gate` locks the pass | This is still caps/core pending and not `ROUTE_SMOKE_PASS`. Next step is to merge this `transition_collar_outer_interface` into the tetra-core shell, then run pressure-only sanity before any viscous RANS |
| pps42/l3 stitched core-shell preflight blocks before Gmsh | The new core-shell probe keeps the stitched handoff gate green, then builds the core-facing inner boundary from `bl_outer_interface`, `transition_collar_outer_interface`, and segmented cap triangles. At pps42/l3 it finds `59,086` faces and `88,602` edges with `557` bad edges: `362` boundary edges and `195` nonmanifold edges. Bad-edge roles are dominated by `transition_collar_outer_interface=475`, with `bl_outer_interface=81` and `te_wall=1`; Gmsh core fill is not attempted | Stratified diagnostics now show the actual nonmanifold blockers are all `transition_collar_outer_interface`, with midpoint `y=17.170–17.206 m`, so the blocker is concentrated at the terminal tip-side outer transition sheet, not at root boundary openings or a generic Gmsh OCC multi-loop patch | `run_phase3_segmented_partial_wing_structured_transition_core_shell_probe()` writes `segmented_partial_wing_structured_transition_core_shell_probe_pps42_l3_stitched_r010_030/structured_transition_core_shell_probe_report.json`; regression test `test_segmented_partial_wing_stitched_core_shell_blocks_nonmanifold_inner_boundary` locks the pre-Gmsh block and now requires bad-edge kind counts, marker-combo counts by kind, midpoint bounds by kind, and edge samples by kind | Do not call Gmsh core fill until `nonmanifold_edge_count=0` for the core-facing inner boundary. Next repair should define a clean tip-side cap receiver or reconstruct the terminal outer transition sheet as a 2-manifold core shell, then re-check TE/closure accounting |
| terminal tip shared-apex shortcut is rejected | A bounded pps4/subdiv1/layers2 probe tried `terminal_tip_closure_policy=shared_apex` with a `0.05 m` tip band, making `158` terminal sidewall closure pyramids share one apex | The shortcut does not solve the topology and creates degenerate pyramid/dual-volume behavior: handoff gate blocks on `structured_handoff_nonmanifold_face_count`, `mixed_dual_subvolume_ratio_exceeds_route_gate`, and hotspot edge-ratio; max dual sub-volume proxy is `>1e16` | Artifact `segmented_partial_wing_structured_transition_core_shell_probe_shared_tip_apex_rejected/structured_transition_core_shell_probe_report.json`; regression test `test_segmented_partial_wing_stitched_core_shell_rejects_shared_tip_apex_shortcut` locks this rejection | Do not use a single apex/fan to close terminal tip. The next repair must be a segmented conformal tip receiver or terminal transition sheet, not a point fan |
| terminal tip receiver shell Build 0 passes | A finite-thickness receiver shell unit with `4` streamwise segments produces marker counts `transition_collar_outer_interface=8`, `terminal_tip_receiver_outer_interface=8`, and `terminal_tip_receiver_side=20` | The artificial shell is two-manifold (`bad_edge_count=0`, `nonmanifold_edge_count=0`) and explicitly does not use a point fan | Artifact `terminal_tip_receiver_shell_unit/terminal_tip_receiver_shell_unit_report.json`; regression test `test_terminal_tip_receiver_shell_unit_is_two_manifold_not_point_fan` locks the contract | Apply this segmented receiver-shell topology to the real pps42/l3 terminal tip outer transition sheet; this unit alone is not a route-smoke mesh |
| pps42/l3 receiver-shell preflight removes terminal nonmanifold but remains boundary-blocked | The real-wing core-shell probe now accepts `terminal_tip_closure_policy=receiver_shell` with `terminal_tip_band_m=0.05`; it removes `7556` terminal tetra boundary faces from the candidate core shell | This clears the terminal `nonmanifold_edge_count` to `0`, confirming GPT Pro's receiver-shell direction, but leaves `624` boundary edges. Component diagnostics show `536` terminal receiver boundary edges across `5` components; the largest component has `204` edges and degree-4/6 branch nodes. Gate remains blocked on `terminal_tip_receiver_shell_boundary_edges_pending` | Artifact `segmented_partial_wing_receiver_shell_core_shell_probe_pps42_l3/structured_transition_core_shell_probe_report.json`; regression test `test_segmented_partial_wing_receiver_shell_removes_pps42_terminal_nonmanifold` locks this nonmanifold-clearing but no-overclaim state and the boundary-component target | Next repair must build explicit receiver boundary closure for the remaining open edges before Gmsh core fill, pressure sanity, or RANS |
| pps42/l3 cycle-cap receiver closure passes core-shell preflight | The receiver-shell core-boundary graph can be decomposed into `50` simple cycles; the cycle-local cap policy covers all `536` terminal receiver boundary edges | Terminal pending edges drop to `0`, inner-boundary `nonmanifold_edge_count=0`, and the core-shell gate is `pass` with `core_report.status=not_run_core_shell_ready`. The remaining `88` boundary edges are root/symmetry accounting, not terminal receiver blocker | Artifact `segmented_partial_wing_receiver_cycle_cap_core_shell_probe_pps42_l3/structured_transition_core_shell_probe_report.json`; regression test `test_segmented_partial_wing_receiver_cycle_caps_close_terminal_boundary` locks the pass | This is still topology preflight only. Next step is an actual Gmsh/core fill attempt and pressure-only sanity before any RANS claim |
| closed-wall wrapper is a near-miss but not a pass | pps12/l16 closed-wall direct prism wrapper has no `>1e7` dual proxy hotspot and non-positive prism count `0`, but root sidewall aspect is about `3589`; pps42/l16 root aspect improves to about `966` but produces `245` non-positive prisms concentrated in `wing_upper` and `te_wall` layers `10-15` | Avoiding exposed partial-BL rim quads helps the dual proxy, but raw full-cap BL extrusion in high-resolution/deep-layer cases self-intersects near aft/TE upper/cap topology | `write_phase3_direct_surface_prism_core_hybrid_su2()` now reports `dual_subvolume_proxy`; `_direct_prism_quality_metrics()` reports non-positive counts by marker/layer; tests lock the pps12/l16 and pps42/l16 tradeoff | Do not promote closed-wall wrapper to route-smoke until it has both positive prisms and root aspect pass, then pressure sanity |

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

## Canonical Hybrid Collar/Core Evidence

- Script entry point:
  `write_phase3_partial_wing_transition_collar_core_hybrid_su2()` in
  `scripts/run_canonical_hybrid_phase3_route_smoke.py`
- Artifact:
  `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0/partial_wing_transition_collar_core_hybrid_pps12_l4/`
- Mesh: `5,376` prisms + `340` pyramids + `8,690` tetra; required physical
  markers are retained and internal `bl_outer_interface` /
  `transition_collar_interface` markers are removed from the final SU2 mesh.
- Pre-solver mixed-element SU2-style subvolume proxy:
  - status: `fail`
  - max CV sub-volume ratio proxy: `437135080576.5444`
  - worst point index: `3234`
  - worst source pair: `tetra_core|tetra_core`
  - worst incident element source counts:
    `{"boundary_layer_prism": 3, "transition_collar_pyramid": 2, "tetra_core": 21}`
- Matching pressure-only SU2 probe:
  `partial_wing_transition_collar_core_hybrid_pps12_l4_pressure_probe/`
  reads the mesh but fails after `3` history rows; solver log reports max CV
  sub-volume ratio `4.37135e11`.
- Engineering read: the explicit transition collar fixed the prism-to-tet
  topology contract, but the pps12/l4 collar/core interface still generates a
  SU2-scale vertex dual-volume pathology before RANS.  The next repair target is
  collar/core local geometry quality and core tet sizing around the collar, not
  marker promotion, NPOIN repair, or conservative numerics.
- Collar-height sweep evidence:
  - `collar_height=1.0e-4 m`: max proxy `4.371350805765444e11`
  - `collar_height=2.0e-4 m`: max proxy `1.852132110316815e11`
  - `collar_height=5.0e-4 m`: max proxy `1.1946561573864338e10`
  - `collar_height=2.0e-3 m`: max proxy `8.865653316600346e9`
  - `collar_height>=2.5e-3 m`: Gmsh reports overlapping facets in this pps12/l4
    setup.
- Interpretation: increasing collar height improves the proxy but does not clear
  the `1e7` route gate before geometry intersection appears.  A thickness-only
  fix is therefore not enough; the next repair must improve collar side-triangle
  aspect/spacing or change transition topology.
- Resolution probe evidence:
  - pps24/l4: `11,520` prisms + `436` pyramids + `12,028` tetra; root sidewall
    aspect `1721.1552977065119`; max proxy `1.3324437641332785e10`
  - pps42/l3: `15,552` prisms + `435` pyramids + `15,705` tetra; root sidewall
    aspect `966.0355808294544`; max proxy `3.3939807886633167e11`; worst
    source pair `tetra_core|tetra_core` with incident transition-collar pyramid;
    hotspot geometry has incident core min edge `5.9999999999848376e-05 m`,
    max edge `1.6789889759830705 m`, and local incident core edge ratio
    `13672.367448040834`; report-level `max_incident_edge_length_ratio` is
    `39059.367143113835`, above the `1000` smoke threshold
  - pps42/l4: `20,736` prisms + `580` pyramids + `16,462` tetra; root sidewall
    aspect `966.0355808294544`; max proxy `1.1725639068823458e10`
- Interpretation: pps42/l3 and pps42/l4 both fix the root sidewall aspect smoke
  gate but not the collar/core dual-volume blocker.  Do not promote either to
  pressure or RANS without a transition-topology repair.

## Closed-Wall Wrapper Evidence

- Script entry point:
  `write_phase3_direct_surface_prism_core_hybrid_su2()` in
  `scripts/run_canonical_hybrid_phase3_route_smoke.py`
- New report field: `dual_subvolume_proxy`
- pps12/l16 evidence:
  - prisms / tetra: `22,880` / `6,032`
  - total BL thickness: `0.004372106472375908 m`
  - prism non-positive count: `0`
  - root sidewall aspect: `3589.4598110984807`
  - max dual proxy: `0.0` at record threshold `1e7`
- pps42/l16 evidence:
  - prisms / tetra: `85,280` / `12,269`
  - total BL thickness: `0.004372106472375908 m`
  - root sidewall aspect: `966.0355808294544`
  - prism non-positive count: `245`
  - non-positive by marker: `wing_upper=124`, `te_wall=121`
  - non-positive by layer: layer `6=10`, `7=12`, `8=17`, `9=26`,
    `10=30`, `11=30`, `12=30`, `13=30`, `14=30`, `15=30`
  - max dual proxy: `28024188.19940058`
- Engineering read: closed-wall extrusion confirms the dual blocker is strongly
  tied to core adjacency at thin/partial BL edges, but raw full-cap extrusion is
  still not a valid active route because the high-resolution/deep-layer case
  introduces inverted prisms around aft/TE upper and TE cap layers.  A viable
  next topology likely needs smoothed cap extrusion, TE/cap layer controls, or a
  graded transition buffer that keeps core tets off the thin BL layers without
  inverting caps.

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
