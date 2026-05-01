# Current Status

## Official Product Line

The formal package-native line today is:

```text
aircraft_assembly (.vsp3)
  -> openvsp_surface_intersection
  -> normalized trimmed STEP
  -> thin_sheet_aircraft_assembly
  -> gmsh_thin_sheet_aircraft_assembly
  -> mesh_handoff.v1
  -> SU2 baseline
  -> su2_handoff.v1
  -> convergence_gate.v1
  -> mesh_study.v1 (optional baseline hardening gate)
```

This is the only route that should currently be treated as a real productized workflow in `hpa_meshing_package`.

## Paused Mesh-Native Main-Wing CFD Line

The experimental main-wing mesh-native CFD line is paused and documented here:

```text
docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md
```

Its current evidence is useful but not a productized CFD claim:

```text
OpenVSP sections -> mesh-native indexed wing -> Gmsh HXT BL mesh -> SU2 smoke
```

Current best mesh evidence:

- `wing_h=0.20 m` HXT BL mesh: `1,125,409` cells, marker-owned, SU2-readable, quality gate pass.
- `wing_h=0.15 m` HXT BL mesh: `1,515,251` cells, quality gate fail due 2 bad BL prisms.

Current physics status:

- no accepted grid-independent CL/CD/Cm;
- no credible HPA drag yet;
- low-Re / BL / transition concerns remain open;
- half-wing symmetry route is not implemented.

Do not continue this line by small mesh-size tweaks until the freeze report is read and the local BL defect is deliberately targeted.

## 2026-04-30 Route Architecture Decision

The high-fidelity line is now explicitly route-matrix first. The long-term goal is arbitrary
HPA main-wing / tail / fairing automation through:

```text
VSP / ESP geometry -> component-family classification -> route selection -> Gmsh -> SU2
```

Do not treat `shell_v4 root_last3` as the product route. It remains a diagnostic and
promotion branch for BL handoff topology. A boundary-layer route can be promoted only after
hpa-mdo owns the transition sleeve, receiver faces, interface loops, and layer-drop event
mapping well enough that Gmsh is only expected to tetrahedralize the core volume.

The machine-readable readiness view is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli route-readiness --out .tmp/runs/component_family_route_readiness
```

This writes `component_family_route_readiness.v1.json` and
`component_family_route_readiness.v1.md`. A committed snapshot is kept under
[`docs/reports/`](reports/). The strategic decision record is
[`docs/research/high_fidelity_route_decision_2026-04-30.md`](../../docs/research/high_fidelity_route_decision_2026-04-30.md).

The pre-mesh dispatch smoke matrix is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli component-family-smoke-matrix --out .tmp/runs/component_family_route_smoke_matrix
```

This writes `component_family_route_smoke_matrix.v1.json` and
`component_family_route_smoke_matrix.v1.md`. It checks that main-wing, tail,
and fairing component families classify and dispatch to registered route
skeletons outside `root_last3`. It does not run Gmsh, BL runtime, SU2,
`mesh_handoff.v1`, `su2_handoff.v1`, or `convergence_gate.v1`.

The main-wing route-readiness report is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-route-readiness --out .tmp/runs/main_wing_route_readiness
```

This writes `main_wing_route_readiness.v1.json` and
`main_wing_route_readiness.v1.md`. The committed snapshot is kept under
`docs/reports/main_wing_route_readiness/`. It is report-only: it reads the
existing main-wing geometry / mesh / SU2 / solver reports and records which
stages are real evidence, which are synthetic wiring evidence, and which are
absent. The current result is `solver_executed_not_converged`: real geometry,
real Gmsh mesh handoff, real SU2 handoff, and a bounded SU2 solver smoke now
exist. The solver reached `history.csv` with exit code 0, but
the 12-iteration `convergence_gate.v1` is `fail` / `not_comparable`; the
non-default solver-budget follow-ups only reach `warn` / `run_only`, so this is
not a converged CFD result. It also confirms the current main-wing SU2
artifacts use the HPA standard `V=6.5 m/s`; any old `V=10` artifact remains
legacy mismatch evidence only. The readiness report now includes separate
`geometry_provenance`, `vspaero_panel_reference`,
`su2_force_marker_audit`, `surface_force_output_audit`,
`openvsp_reference_geometry_gate`, and `lift_acceptance_diagnostic` stages:
OpenVSP provenance is available (`Y_Rotation=3 deg`, cambered airfoils, zero
parsed local twist), VSPAERO panel reference evidence is available at
`CLtot=1.287645495943`, and the OpenVSP-reference geometry gate records
`Bref=33.0 m` as the span provenance. The force-marker audit is real evidence
with marker checks passing but scope `warn`; the surface-force output audit now
passes the output-retention checks because `surface.csv` and
`forces_breakdown.dat` are both retained under the 80-iteration raw solver
artifacts. SU2 lift acceptance remains blocked because the selected
current-route smoke has `CL=0.263161913`, about `4.89x` lower than the VSPAERO
panel baseline and below the main-wing `CL > 1.0` acceptance gate for the HPA
operating point. The retained `surface.csv` / `forces_breakdown.dat` artifacts
make force-breakdown debugging possible, but the next engineering blocker is
now geometry-side station-seam topology plus panel/SU2 lifting-surface semantics,
not a self-invented solver-iteration budget. The panel/SU2 semantics reports
now source-label VSPAERO `CLi` as the inviscid surface-integration component
and `CLiw` / `CLwtot` as the wake/free-stream induced outputs, so future debug
should not describe the high panel `CL` as a pure wake-column artifact. The
station fixture records 4 boundary edges and 2 nonmanifold edges at
OpenVSP sections 3 and 4. The BRep hotspot probe confirms that station curves
36 and 50 map cleanly to STEP edge ids after the expected mm-to-m scale and
that owner surfaces 12 / 13 / 19 / 20 have closed, connected, ordered wires;
however, PCurve consistency / same-parameter checks remain suspect. The
same-parameter feasibility probe then attempts in-memory `BRepLib.SameParameter`
from `1e-7` through `1e-3` and does not recover those station checks. The
ShapeFix feasibility probe extends that negative result across 25 in-memory
`ShapeFix_Edge` attempts: five operations over five tolerances, with zero
recovered station checks. The profile parametrization audit now correlates the
current profile-resample candidate back to its CSM section segments: across the
two target stations, all 6 station-edge PCurve checks fail, 4 short station
curves match terminal `linseg` fragments, and 2 long station curves match
spline rest arcs. The side-aware parametrization probe then preserves TE/LE
anchors, resamples upper/lower sides independently to 30 / 30 points, and
materializes a `1 volume / 32 surfaces` full-span candidate with no target
station cap faces. The side-aware BRep validation probe then selects target
station edges by candidate station-y geometry (`source_fixture_tags_replayed=false`):
the candidate remains `1 volume / 32 surfaces`, 6 station edges and 12 owner
faces are checked, PCurves are present, and owner-face wires are valid, but all
6 station edges still fail the combined PCurve consistency checks. The
side-aware PCurve residual diagnostic then samples all 12 edge-face PCurves:
sampled 3D-vs-PCurve residual max is `0.0 m`, but all 12 ShapeAnalysis /
same-parameter / vertex-tolerance flags still fail and the PCurves are
unbounded `Geom2d_Line` domains. The side-aware candidate is therefore not
mesh-ready. The side-aware metadata repair probe then runs the bounded
SameParameter / ShapeFix repair gate on those six station edges: 5
`BRepLib.SameParameter` tolerances and 25 `ShapeFix_Edge`
operation/tolerance attempts all have `recovered_attempt_count = 0`. The
side-aware PCurve metadata builder probe then tests four bounded-existing-PCurve
strategies: all 12 edge-face PCurve domains can be made bounded, but 0 / 12
edge-face pairs pass the full ShapeAnalysis metadata gate. The side-aware
projected PCurve builder probe then tests `GeomProjLib.Curve2d`, sampled
`GeomAPI_ProjectPointOnSurf + Geom2dAPI_Interpolate`, and sampled
`GeomAPI_ProjectPointOnSurf + Geom2dAPI_PointsToBSpline`: all 36
strategy/edge-face operations build bounded PCurves, all 36 endpoint orientation
gates pass, and sampled projection residual max is
`1.8343894894033213e-15 m`, but 0 / 12 edge-face pairs pass the full
ShapeAnalysis metadata gate. The next repair target is therefore upstream
section parametrization or export PCurve metadata generation for the side-aware
export, rather than mesh or solver budget. The side-aware export opcode variant
probe then tests report-local OpenCSM opcode changes: `upper_lower_spline_split`
materializes as `1 volume / 52 surfaces` but still does not recover the station
BRep / PCurve gate, while `all_linseg` materializes as `1 volume / 582 surfaces`
and is stopped by the surface-count guard. Simple opcode variants are therefore
negative-control evidence, not a product repair. The export metadata source
audit then records that hpa-mdo owns CSM section coordinates, opcode policy,
rule grouping, and the `DUMP` invocation, but rule-loft PCurve metadata, EGADS
STEP export metadata, and OCCT ShapeAnalysis truth are external to the current
CSM-writer layer. The format-boundary probe now materializes the same side-aware
CSM through STEP, BREP, and EGADS; STEP remains station-metadata suspect, BREP is
Gmsh-importable for station-curve selection but not yet comparable because the
hotspot gate still uses a STEP reader, and EGADS is unavailable to the current
Gmsh/OCC importer. The next gate is a BREP-capable station hotspot reader or
owned OCC import gate. The export-source audit
then traces those target
stations back to `rebuild.csm`: the provider export uses one OpenCSM `rule`
over 11 sketch sections, and curves 36 / 50 map to internal rule sections at
`y=-10.5 m` and `y=13.5 m`. The mesh-quality hotspot audit now partitions the
real-mesh worst-tet sample: 15 / 20 sampled worst tets are nearest to
`farfield`, while 5 / 20 are nearest to `main_wing` surfaces 19 / 29 / 32; the
surface-19 hotspot overlaps the station-seam entity trace surface set
`12 / 13 / 19 / 20` with candidate curves 36 / 50. This is mesh-risk evidence,
not convergence evidence, and it reinforces that the current readiness next action is
`add_brep_capable_station_hotspot_reader_or_occ_import_gate`.

The main-wing VSPAERO panel reference probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-vspaero-panel-reference-probe --out .tmp/runs/main_wing_vspaero_panel_reference_probe
```

This writes `main_wing_vspaero_panel_reference_probe.v1.json` and
`main_wing_vspaero_panel_reference_probe.v1.md`. The committed result reads the
existing fixed-alpha VSPAERO panel baseline at
`output/dihedral_sweep_fixed_alpha_smoke_rerun/origin_vsp_panel_fixed_alpha_baseline/`.
It is `panel_reference_available` at the HPA standard `V=6.5 m/s`, with
`CLtot=1.287645495943` at `alpha=0 deg`. This is lower-order panel evidence,
not high-fidelity CFD, but it supports the engineering sanity gate that a
main-wing route claiming convergence at this operating point must not pass with
`CL <= 1.0`; the current selected SU2 smoke is about `4.89x` lower in `CL`.
The source-backed panel/SU2 semantics audit now records `CLi` as an inviscid
surface-integration component, not a wake-induced column; `CLiw` / `CLwtot`
carry the wake/free-stream induced output. This keeps the next debug focused on
lifting-surface / exported-geometry / SU2 wall semantics rather than a mistaken
`CLi` label.

The main-wing SU2 force-marker audit is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-su2-force-marker-audit --out .tmp/runs/main_wing_su2_force_marker_audit
```

This writes `main_wing_su2_force_marker_audit.v1.json` and
`main_wing_su2_force_marker_audit.v1.md`. The committed snapshot under
`docs/reports/main_wing_su2_force_marker_audit/` reads the OpenVSP-reference
SU2 handoff and runtime config. Current result is `warn`: `MARKER_EULER`,
`MARKER_MONITORING`, and `MARKER_PLOTTING` all include `main_wing`, `MARKER_FAR`
includes `farfield`, mesh marker counts are positive (`main_wing=2424` surface
elements, `farfield=5376`), and `V=6.5 m/s` plus OpenVSP reference area/chord
are preserved. The warning is scope-related: the current solver smoke uses an
Euler wall condition and the reference moment origin is still not formally
certified, so this audit supports force-marker ownership but does not make the
route viscous-CFD-ready.

The main-wing surface-force output audit is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-surface-force-output-audit --out .tmp/runs/main_wing_surface_force_output_audit
```

This writes `main_wing_surface_force_output_audit.v1.json` and
`main_wing_surface_force_output_audit.v1.md`. The committed snapshot under
`docs/reports/main_wing_surface_force_output_audit/` reads the OpenVSP-reference
80-iteration solver smoke, its raw solver log, and the VSPAERO panel reference.
Current result is `warn`: the solver log advertises both `surface.csv` and
`forces_breakdown.dat`; the committed raw-solver artifact directory now retains
`history.csv`, `solver.log`, `surface.csv`, and `forces_breakdown.dat`. This
means force-marker ownership and surface-output retention are established, and
panel/SU2 force-breakdown debugging is now ready from an artifact-retention
standpoint. The audit still observes `V=6.5 m/s`, derives
`main_wing_lift_acceptance_status=fail` from `CL=0.263161913`, and keeps the
VSPAERO panel baseline visible at `CLtot=1.287645495943`; none of this is a
convergence claim.

The main-wing mesh-quality hotspot audit is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-mesh-quality-hotspot-audit --out .tmp/runs/main_wing_mesh_quality_hotspot_audit
```

This writes `main_wing_mesh_quality_hotspot_audit.v1.json` and
`main_wing_mesh_quality_hotspot_audit.v1.md`. The committed snapshot under
`docs/reports/main_wing_mesh_quality_hotspot_audit/` reads the real mesh
handoff quality metrics, `mesh_metadata.json`, `hotspot_patch_report.json`,
`surface_patch_diagnostics.json`, and the Gmsh defect entity trace. Current
result is `mesh_quality_hotspots_localized`: the real mesh still has
`78` ill-shaped tets and `min_gamma=8.131677887160085e-07`; the bounded
worst-tet sample is mostly farfield (`15 / 20`) but still includes main-wing
hotspots on surfaces `19 / 29 / 32`, with surface `19` overlapping the traced
station-seam surface set. This supports fixing station export / section
parametrization before spending more solver-iteration budget; it does not claim
that mesh quality explains the whole panel/SU2 lift gap.

The main-wing station-seam BRep hotspot probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-brep-hotspot-probe --out .tmp/runs/main_wing_station_seam_brep_hotspot_probe
```

This writes `main_wing_station_seam_brep_hotspot_probe.v1.json` and
`main_wing_station_seam_brep_hotspot_probe.v1.md`. The committed snapshot under
`docs/reports/main_wing_station_seam_brep_hotspot_probe/` reads the real
main-wing normalized STEP plus the station-topology fixture and records
`brep_hotspot_captured_station_edges_suspect`. Current evidence localizes the
hotspot to station curves 36 and 50: both curves map to same-number STEP edges
after `scale_to_output_units=0.001`, their owner faces are 12 / 13 and 19 / 20,
and all target owner wires are closed, connected, and ordered. PCurves are
present, but curve-3D-with-PCurve, same-parameter-by-face, and
vertex-tolerance-by-face checks remain suspect. The report is diagnostic only:
it does not run Gmsh, SU2, or change production defaults.

The main-wing station-seam same-parameter feasibility probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-same-parameter-feasibility --out .tmp/runs/main_wing_station_seam_same_parameter_feasibility
```

This writes `main_wing_station_seam_same_parameter_feasibility.v1.json` and
`main_wing_station_seam_same_parameter_feasibility.v1.md`. The committed
snapshot under `docs/reports/main_wing_station_seam_same_parameter_feasibility/`
records `same_parameter_repair_not_recovered`: baseline PCurves are present,
but baseline same-parameter / curve-3D-with-PCurve / vertex-tolerance checks do
not all pass, and an in-memory `BRepLib.SameParameter` tolerance sweep from
`1e-7` through `1e-3` does not recover either target curve. This is evidence
against treating a simple OCCT same-parameter pass as the main-wing station
repair; the next gate is inspecting or rebuilding the station PCurves /
station-seam geometry before trying to promote a compound meshing policy.

The main-wing station-seam ShapeFix feasibility probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-shape-fix-feasibility --out .tmp/runs/main_wing_station_seam_shape_fix_feasibility
```

This writes `main_wing_station_seam_shape_fix_feasibility.v1.json` and
`main_wing_station_seam_shape_fix_feasibility.v1.md`. The committed snapshot
under `docs/reports/main_wing_station_seam_shape_fix_feasibility/` records
`shape_fix_repair_not_recovered`: baseline PCurves are present, but station
checks do not all pass, and five `ShapeFix_Edge` operation families over
tolerances `1e-7` through `1e-3` recover zero targets. This is evidence against
continuing generic OCCT edge-fix sweeps; the next gate is rebuilding station
PCurves or changing the station-seam export strategy before meshing-policy or
solver-budget work.

The main-wing station-seam export-source audit is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-export-source-audit --out .tmp/runs/main_wing_station_seam_export_source_audit
```

This writes `main_wing_station_seam_export_source_audit.v1.json` and
`main_wing_station_seam_export_source_audit.v1.md`. The committed snapshot
under `docs/reports/main_wing_station_seam_export_source_audit/` records
`single_rule_internal_station_export_source_confirmed`: the generated
`rebuild.csm` contains one multi-section `rule` over 11 sketch sections, and
the two unrecovered station defects map to internal rule sections. This is
evidence for an export-strategy probe next; it is not a production default
change and does not run Gmsh, SU2, or convergence gates.

The main-wing station-seam export-strategy probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-export-strategy-probe --out .tmp/runs/main_wing_station_seam_export_strategy_probe --materialize-candidates
```

This writes `main_wing_station_seam_export_strategy_probe.v1.json` and
`main_wing_station_seam_export_strategy_probe.v1.md`, plus candidate CSM/STEP
artifacts under the report directory. The committed snapshot records
`export_strategy_candidate_materialized_but_topology_risk`: split-at-defect
rules move target rule sections 2 and 9 to rule boundaries, but the no-union
candidate imports as 3 volumes, while the union candidate imports as 1 volume
with y-bounds ending at `13.5 m` instead of the expected `16.5 m`. This blocks
split-bay promotion; the next gate is internal-cap inspection or a PCurve /
export rebuild strategy before mesh handoff or solver-budget work.

The main-wing split-candidate internal-cap probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-internal-cap-probe --out .tmp/runs/main_wing_station_seam_internal_cap_probe
```

This writes `main_wing_station_seam_internal_cap_probe.v1.json` and
`main_wing_station_seam_internal_cap_probe.v1.md`. The committed snapshot
records `split_candidate_internal_cap_risk_confirmed`: the no-union candidate
has duplicate station cap faces at both `y=-10.5 m` and `y=13.5 m` and remains
3 volumes; the union candidate is one volume but truncates the right span and
leaves 6 cap fragments at `y=13.5 m`. This confirms the split-bay strategy is
negative evidence, not a mesh-handoff candidate.

The main-wing profile-resample export strategy probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-profile-resample-strategy-probe --out .tmp/runs/main_wing_station_seam_profile_resample_strategy_probe --materialize-candidate
```

This writes `main_wing_station_seam_profile_resample_strategy_probe.v1.json`,
`main_wing_station_seam_profile_resample_strategy_probe.v1.md`, and candidate
CSM/STEP/log artifacts. The committed snapshot records
`profile_resample_candidate_materialized_needs_brep_validation`: source section
profile counts were `57/59`, the candidate uniformizes them to `59`, keeps a
single OpenCSM `rule`, imports as `1 volume / 32 surfaces`, preserves full span,
and has zero target-station cap faces. This is not mesh-ready; the next gate is
station BRep/PCurve validation on the candidate STEP.

The main-wing profile-resample BRep validation probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-profile-resample-brep-validation-probe --out .tmp/runs/main_wing_station_seam_profile_resample_brep_validation_probe
```

This writes
`main_wing_station_seam_profile_resample_brep_validation_probe.v1.json` and
`main_wing_station_seam_profile_resample_brep_validation_probe.v1.md`. The
committed snapshot records
`profile_resample_candidate_station_brep_edges_suspect`: station seam edges are
selected from the candidate STEP by target `y` geometry, not replayed from the
old station-fixture curve/surface ids. Six station edges are found across
`y=-10.5 m` and `y=13.5 m`; PCurves are present and owner-face wires are
closed/connected/ordered, but curve-3D-with-PCurve, same-parameter-by-face, and
vertex-tolerance-by-face checks remain suspect. This keeps the profile-resample
candidate out of mesh handoff until the station PCurve/export issue is repaired
or explained.

The main-wing profile-resample repair feasibility probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-profile-resample-repair-feasibility-probe --out .tmp/runs/main_wing_station_seam_profile_resample_repair_feasibility_probe
```

This writes
`main_wing_station_seam_profile_resample_repair_feasibility_probe.v1.json` and
`main_wing_station_seam_profile_resample_repair_feasibility_probe.v1.md`. The
committed snapshot records
`profile_resample_station_shape_fix_repair_not_recovered`: the six
candidate-selected station edges all have PCurves, but same-parameter,
curve-3D-with-PCurve, and vertex-tolerance checks fail at baseline; 25 bounded
in-memory ShapeFix / SameParameter operation-tolerance attempts produce
`recovered_attempt_count = 0`. This is engineering evidence that the next fix
belongs in export / section parametrization, not direct mesh handoff, solver
budget, or a surface-id patch.

The main-wing profile parametrization audit is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-profile-parametrization-audit --out .tmp/runs/main_wing_station_seam_profile_parametrization_audit
```

This writes
`main_wing_station_seam_profile_parametrization_audit.v1.json` and
`main_wing_station_seam_profile_parametrization_audit.v1.md`. The committed
snapshot records
`profile_parametrization_seam_fragment_correlation_observed`: the six
candidate-selected station edges still all fail PCurve consistency, four short
station curves match the candidate CSM terminal `linseg` fragments, and two
long station curves match the spline rest arcs. This is report-only geometry
evidence for the next export change; it is not a mesh-handoff, solver, or
convergence claim.

The main-wing side-aware parametrization probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-side-aware-parametrization-probe --out .tmp/runs/main_wing_station_seam_side_aware_parametrization_probe --materialize-candidate
```

This writes
`main_wing_station_seam_side_aware_parametrization_probe.v1.json`,
`main_wing_station_seam_side_aware_parametrization_probe.v1.md`, and candidate
CSM/STEP/log artifacts. The committed snapshot records
`side_aware_parametrization_candidate_materialized_needs_brep_validation`: all
sections are resampled to 30 upper-side and 30 lower-side points, TE/LE anchors
are preserved exactly, the candidate materializes as `1 volume / 32 surfaces`,
full span is preserved, and no target-station cap faces are observed. This is
not mesh-ready; the next gate is BRep/PCurve validation on the side-aware STEP.

The main-wing side-aware BRep validation probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-side-aware-brep-validation-probe --out .tmp/runs/main_wing_station_seam_side_aware_brep_validation_probe
```

This writes `main_wing_station_seam_side_aware_brep_validation_probe.v1.json`
and `main_wing_station_seam_side_aware_brep_validation_probe.v1.md`. The
committed snapshot records `side_aware_candidate_station_brep_edges_suspect`:
station edges are selected geometrically from the side-aware candidate STEP
(`source_fixture_tags_replayed=false`), 6 station edges and 12 owner faces are
checked, PCurves are present, and owner-face wires are closed / connected /
ordered. However, all 6 station edges fail curve-3D-with-PCurve,
same-parameter-by-face, and vertex-tolerance-by-face checks. This keeps the
route blocked before Gmsh mesh handoff and shifts the next action to repairing
side-aware OpenCSM/export PCurve generation.

The main-wing side-aware PCurve residual diagnostic is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-side-aware-pcurve-residual-diagnostic --out .tmp/runs/main_wing_station_seam_side_aware_pcurve_residual_diagnostic
```

This writes
`main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1.json` and
`main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1.md`. The
committed snapshot records
`side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail`:
all 12 selected edge-face pairs have sampled 3D-vs-PCurve residual max
`0.0 m`, so the current blocker is not gross PCurve geometric separation.
However, all 12 ShapeAnalysis / same-parameter / vertex-tolerance flags still
fail and all sampled PCurves are unbounded `Geom2d_Line` domains. This keeps the
route blocked before Gmsh mesh handoff; the next gate is a bounded
same-parameter / metadata repair probe on the side-aware candidate.

The main-wing side-aware metadata repair probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-side-aware-metadata-repair-probe --out .tmp/runs/main_wing_station_seam_side_aware_metadata_repair_probe
```

This writes `main_wing_station_seam_side_aware_metadata_repair_probe.v1.json`
and `main_wing_station_seam_side_aware_metadata_repair_probe.v1.md`. The
committed snapshot records
`side_aware_station_metadata_repair_not_recovered`: six target station edges
are evaluated, the preceding residual diagnostic context is preserved
(`max_sample_distance_m=0.0`, `shape_analysis_flag_failure_count=12`), five
`BRepLib.SameParameter` tolerances and 25 `ShapeFix_Edge`
operation/tolerance attempts all report `recovered_attempt_count=0`. This keeps
the route blocked before Gmsh mesh handoff; the next gate is a side-aware
station PCurve rewrite or export-metadata builder, not more generic
SameParameter/ShapeFix sweeps or solver budget.

The main-wing side-aware PCurve metadata builder probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-side-aware-pcurve-metadata-builder-probe --out .tmp/runs/main_wing_station_seam_side_aware_pcurve_metadata_builder_probe
```

This writes
`main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1.json` and
`.md`. The committed result is
`side_aware_station_pcurve_metadata_builder_partial`: baseline has 12 / 12
PCurves present but 0 / 12 bounded domains and 0 / 12 full metadata passes.
Four bounded-existing-PCurve strategies bound all 12 PCurve domains, but still
leave 0 / 12 edge-face pairs passing same-parameter,
curve-3D-with-PCurve, and vertex-tolerance checks. This is partial CAD
metadata progress only, not mesh readiness; the next gate is projected/sampled
PCurve construction with vertex/orientation validation.

The main-wing side-aware projected PCurve builder probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-side-aware-projected-pcurve-builder-probe --out .tmp/runs/main_wing_station_seam_side_aware_projected_pcurve_builder_probe
```

This writes
`main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1.json` and
`.md`. The committed result is
`side_aware_station_projected_pcurve_builder_partial`: 36 / 36 projected or
sampled PCurve operations materialize bounded PCurves and pass endpoint
orientation, with sampled projection residual max
`1.8343894894033213e-15 m`, but the full ShapeAnalysis metadata gate remains
0 / 12. SameParameter / SameRange flags are therefore diagnostic only, not
truth-source pass criteria. The route remains blocked before Gmsh mesh handoff;
the next repair should move upstream to section parametrization or export
PCurve metadata generation.

The main-wing side-aware export opcode variant probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-side-aware-export-opcode-variant-probe --out .tmp/runs/main_wing_station_seam_side_aware_export_opcode_variant_probe --materialize-variants
```

This writes
`main_wing_station_seam_side_aware_export_opcode_variant_probe.v1.json` and
`.md`. The committed result is
`side_aware_export_opcode_variant_not_recovered`: the
`upper_lower_spline_split` report-local candidate materializes as
`1 volume / 52 surfaces` but remains station-PCurve suspect, while the
`all_linseg` candidate materializes as `1 volume / 582 surfaces` and is stopped
by the surface-count guard before expensive validation. This is evidence that
simple OpenCSM opcode switching is not the product repair; the next gate is
inspection of the export PCurve metadata generation path itself.

The main-wing station-seam export metadata source audit is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-export-metadata-source-audit --out .tmp/runs/main_wing_station_seam_export_metadata_source_audit --external-src-root /Users/linyuan/.local/esp/current/EngSketchPad
```

This writes `main_wing_station_seam_export_metadata_source_audit.v1.json` and
`.md`. The committed result is
`export_metadata_generation_source_boundary_captured`: hpa-mdo owns CSM source
construction only (`section_coordinates`, `sketch_opcode_policy`,
`rule_grouping`, `dump_invocation`), while rule-loft PCurve metadata, EGADS STEP
export metadata, and OCCT ShapeAnalysis semantics are external to the current
CSM writers. Because the opcode variants are negative controls, the follow-up
format-boundary probe compares the same side-aware candidate through STEP, BREP,
and EGADS exports before any mesh handoff or solver-budget work.

The main-wing station-seam export format-boundary probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-station-seam-export-format-boundary-probe --out .tmp/runs/main_wing_station_seam_export_format_boundary_probe --formats step brep egads --materialize-formats --external-src-root /Users/linyuan/.local/esp/current/EngSketchPad
```

This writes `main_wing_station_seam_export_format_boundary_probe.v1.json` and
`.md`. The committed result is
`export_format_boundary_step_suspect_non_step_validation_unavailable`: STEP,
BREP, and EGADS all materialize from the same side-aware CSM; STEP remains
station-metadata suspect, BREP can be imported by Gmsh for station-curve
selection, and EGADS is not importable by the current Gmsh/OCC path. The current
BREP validation is not comparable because the existing hotspot reader still uses
a STEP reader internally. Do not treat BREP as failed or recovered until a
BREP-capable station hotspot reader or owned OCC import gate exists.

The first real fairing geometry smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-geometry-smoke --out .tmp/runs/fairing_solid_real_geometry_smoke
```

This writes `fairing_solid_real_geometry_smoke.v1.json` and
`fairing_solid_real_geometry_smoke.v1.md`. It consumes the external
`HPA-Fairing-Optimization-Project` `best_design.vsp3`, selects a `Fuselage`,
materializes a normalized STEP through `openvsp_surface_intersection`, and
observes closed-solid topology. The current committed result is
`geometry_smoke_pass` with `1 body / 8 surfaces / 1 volume`. It does not run
Gmsh meshing, SU2, or convergence, so the next blocker is real fairing mesh
handoff.

The first real fairing mesh handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-mesh-handoff-probe --out .tmp/runs/fairing_solid_real_mesh_handoff_probe
```

This writes `fairing_solid_real_mesh_handoff_probe.v1.json` and
`fairing_solid_real_mesh_handoff_probe.v1.md`. The current committed result is
`mesh_handoff_pass`: the real fairing VSP geometry writes `mesh_handoff.v1`
with `fairing_solid` and `farfield` markers using coarse probe sizing
(`node_count=29394`, `volume_element_count=153251` in the latest snapshot).
It still does not run SU2 or convergence, so the next blocker is real fairing
SU2 handoff materialization.

The first real fairing SU2 handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-su2-handoff-probe --out .tmp/runs/fairing_solid_real_su2_handoff_probe --source-mesh-probe-report docs/reports/fairing_solid_real_mesh_handoff_probe/fairing_solid_real_mesh_handoff_probe.v1.json
```

This writes `fairing_solid_real_su2_handoff_probe.v1.json` and
`fairing_solid_real_su2_handoff_probe.v1.md`. The current committed result is
`su2_handoff_written`: the real fairing `mesh_handoff.v1` materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` with a component-owned
`fairing_solid` force marker. It still does not run `SU2_CFD` or convergence.
`reference_geometry_status=warn`, so coefficient credibility remains blocked
until the fairing reference policy is explicit and a solver/convergence gate is
recorded.

The fairing reference-policy probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-reference-policy-probe --out .tmp/runs/fairing_solid_reference_policy_probe
```

This writes `fairing_solid_reference_policy_probe.v1.json` and
`fairing_solid_reference_policy_probe.v1.md`. It reads the neighboring fairing
optimization project under `/Volumes/Samsung SSD/HPA-Fairing-Optimization-Project`.
The committed result is `reference_mismatch_observed`: the external fairing
policy uses `REF_AREA=1.0`, `REF_LENGTH=2.82880659`, and the HPA standard
`V=6.5`, while the legacy pre-standard hpa-mdo real fairing SU2 handoff artifact
used `REF_AREA=100`, `REF_LENGTH=1`, and `V=10`. `V=10` is historical mismatch
evidence, not the current HPA standard.

The fairing reference-override SU2 handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-reference-override-su2-handoff-probe --out .tmp/runs/fairing_solid_reference_override_su2_handoff_probe
```

This writes `fairing_solid_reference_override_su2_handoff_probe.v1.json` and
`fairing_solid_reference_override_su2_handoff_probe.v1.md`. The current
committed result is `su2_handoff_written` with
`reference_override_status=applied_with_moment_origin_warning`: `REF_AREA=1.0`,
`REF_LENGTH=2.82880659`, `V=6.5`, and the `fairing_solid` force marker are now
materialized into a real fairing `su2_handoff.v1`. Solver history and
convergence are still absent, and the borrowed zero moment origin remains a
blocker for moment coefficients.

Package-native SU2 runtime defaults now follow the same HPA flow standard:
`velocity_mps=6.5`, `density_kgpm3=1.225`, `temperature_k=288.15`, and
`dynamic_viscosity_pas=1.7894e-5`. Editable operator-facing values live under
`su2.flow_conditions` in the YAML config.

The first route-specific fairing mesh-handoff smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-mesh-handoff-smoke --out .tmp/runs/fairing_solid_mesh_handoff_smoke
```

This writes `fairing_solid_mesh_handoff_smoke.v1.json` and
`fairing_solid_mesh_handoff_smoke.v1.md`. It runs real Gmsh for a synthetic
closed-solid fairing fixture and emits `mesh_handoff.v1`. It still does not run
SU2, does not emit `su2_handoff.v1`, and does not emit `convergence_gate.v1`.
It does include a component-owned `fairing_solid` marker in the mesh-handoff
evidence.

The first fairing SU2 handoff materialization smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-su2-handoff-smoke --out .tmp/runs/fairing_solid_su2_handoff_smoke
```

This writes `fairing_solid_su2_handoff_smoke.v1.json` and
`fairing_solid_su2_handoff_smoke.v1.md`. It consumes the synthetic closed-solid
fairing `mesh_handoff.v1` and materializes `su2_handoff.v1`, `mesh.su2`, and
`su2_runtime.cfg` without executing `SU2_CFD`. It consumes the component-owned
`fairing_solid` wall marker; real-geometry SU2 handoff is tracked by the
separate real probe, while solver history and convergence remain missing.

The first main-wing ESP-rebuilt geometry smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-esp-rebuilt-geometry-smoke --out .tmp/runs/main_wing_esp_rebuilt_geometry_smoke
```

This writes `main_wing_esp_rebuilt_geometry_smoke.v1.json` and
`main_wing_esp_rebuilt_geometry_smoke.v1.md`. It consumes
`data/blackcat_004_origin.vsp3`, selects the OpenVSP `Main Wing` as
`main_wing`, and materializes an ESP-normalized thin lifting-surface STEP. The
current committed result is `geometry_smoke_pass` with `surface_count=32` and
`volume_count=1`. It still does not run Gmsh, does not emit
`mesh_handoff.v1`, does not run SU2, and does not prove solver credibility.

The first real main-wing mesh handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-real-mesh-handoff-probe --out .tmp/runs/main_wing_real_mesh_handoff_probe --global-min-size 0.35 --global-max-size 1.4
```

This writes `main_wing_real_mesh_handoff_probe.v1.json` and
`main_wing_real_mesh_handoff_probe.v1.md`. The current committed result is
`mesh_handoff_pass`: provider geometry is materialized with `surface_count=32`
and `volume_count=1`, and the coarse bounded Gmsh route writes
`mesh_handoff.v1` with `main_wing`, `farfield`, and `fluid` groups. The current
snapshot has `node_count=97299`, `volume_element_count=584460`, and
`mesh3d_watchdog_status=completed_without_timeout`. This is still a bounded
coarse probe, not production sizing, and it does not run BL runtime. The CLI
exposes probe-local `--global-min-size` and `--global-max-size` knobs for
sizing-sensitivity experiments; these do not change the production route
default.

The first real main-wing SU2 handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-real-su2-handoff-probe --out .tmp/runs/main_wing_real_su2_handoff_probe --source-mesh-probe-report docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.json
```

This writes `main_wing_real_su2_handoff_probe.v1.json` and
`main_wing_real_su2_handoff_probe.v1.md`. The current committed result is
`su2_handoff_written`: the real main-wing mesh handoff materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` with a component-owned
`main_wing` force marker and `V=6.5 m/s`. It does not execute `SU2_CFD` and it
keeps `reference_geometry_status=warn`.

The first real main-wing solver smoke probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-real-solver-smoke-probe --out .tmp/runs/main_wing_real_solver_smoke_probe --source-su2-probe-report docs/reports/main_wing_real_su2_handoff_probe/main_wing_real_su2_handoff_probe.v1.json --timeout-seconds 180
```

This writes `main_wing_real_solver_smoke_probe.v1.json`,
`main_wing_real_solver_smoke_probe.v1.md`, and a `convergence_gate.v1.json`
artifact. The current committed result is
`solver_executed_but_not_converged`: `SU2_CFD` exits successfully and writes
`history.csv`, but the iterative gate fails after 12 rows, coefficient tails are
still drifting, and the reference gate remains `warn`. Treat this as a solver
smoke / blocker artifact, not a converged CFD result.

A non-default 40-iteration follow-up artifact is kept under
`docs/reports/main_wing_real_solver_smoke_probe_iter40/`. It uses the same real
mesh/SU2 handoff route with probe-local `runtime_max_iterations=40` and
`V=6.5 m/s`. The result improves to `convergence_gate_status=warn` and
`convergence_comparability_level=run_only`, with `final_iteration=39`,
`CL ~= 0.2719`, and `CD ~= 0.0260`, but it is still
`solver_executed_but_not_converged` because residual drop remains below the gate
threshold, reference geometry remains `warn`, and the main-wing lift acceptance
gate requires `CL > 1.0` at the HPA standard `V=6.5 m/s`.

An explicit OpenVSP/VSPAERO reference-policy SU2 handoff snapshot is kept under
`docs/reports/main_wing_openvsp_reference_su2_handoff_probe/`. It uses the same
real main-wing mesh handoff but requests `reference_policy=openvsp_geometry_derived`,
producing `REF_AREA=35.175`, `REF_LENGTH=1.0425`,
`REF_ORIGIN_MOMENT=(0,0,0)`, `V=6.5 m/s`, and the component-owned `main_wing`
force marker. This is a materialized handoff only: no solver or convergence
claim is made, and production defaults are unchanged.

The matching bounded solver smoke is kept under
`docs/reports/main_wing_openvsp_reference_solver_smoke_probe/`. It executes
`SU2_CFD` from the OpenVSP-reference handoff and exits with code 0, but the
gate is still `fail/not_comparable` after 12 iterations. Final reported
coefficients are `CL ~= 0.2603`, `CD ~= 0.01859`, and `CMy ~= -0.2033`.
This is evidence that OpenVSP reference normalization materializes and changes
coefficient scaling, not evidence of convergence.

A non-default 40-iteration OpenVSP-reference follow-up is kept under
`docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter40/`. It uses
the same OpenVSP/VSPAERO reference-policy handoff with probe-local
`runtime_max_iterations=40` and `V=6.5 m/s`. The result improves to
`convergence_gate_status=warn` and `convergence_comparability_level=run_only`,
with `final_iteration=39`, `CL ~= 0.2679`, `CD ~= 0.02558`, and
`CMy ~= -0.2131`, but it remains `solver_executed_but_not_converged`.

An 80-iteration OpenVSP-reference budget probe is kept under
`docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/`. It also
remains `solver_executed_but_not_converged`, now with
`convergence_gate_status=fail` and
`convergence_comparability_level=not_comparable` after the CL gate is applied.
It reaches `final_iteration=79`, `CL ~= 0.2632`, `CD ~= 0.02497`, and
`CMy ~= -0.2097`. The useful engineering signal is that coefficient stability
is now tight and both `surface.csv` and `forces_breakdown.dat` are retained,
while median residual log drop is still only about `0.358` against the `0.5`
pass threshold; this is still not convergence.
The SU2 preprocessing log also reports high mesh-quality ratios
(`CV Face Area Aspect Ratio max ~= 377.9`, `CV Sub-Volume Ratio max ~= 13256`),
so the next numerics work should inspect mesh quality and local sizing rather
than only raising the iteration budget again.

The main-wing solver-validation policy is now recorded under
`docs/contracts/main_wing_solver_validation_policy.v1.md`, with a committed
snapshot under `docs/reports/main_wing_solver_validation_policy/`. It clarifies
that the 12/40/80-iteration artifacts are route-smoke and diagnostic evidence
only. SU2's own documentation and tutorials use explicit residual or
coefficient-Cauchy stopping criteria with much larger iteration ceilings
(`9999` or higher; coefficient windows such as 50-100 samples). Therefore this
project must not invent a convergence standard from the current short smoke
budgets. Engineering convergence claims need a source-backed solver budget and
stopping policy before they can be used for validation.

The main-wing geometry-provenance probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-geometry-provenance-probe --out .tmp/runs/main_wing_geometry_provenance_probe
```

This writes `main_wing_geometry_provenance_probe.v1.json` and
`main_wing_geometry_provenance_probe.v1.md`. The current committed result is
`provenance_available`: the source OpenVSP `Main Wing` has
`Y_Rotation=3 deg`, six parsed sections with zero local twist, and embedded
cambered airfoil coordinates (`FX 76-MP-140` across most sections and
`CLARK-Y 11.7% smoothed` at the tip). Engineering interpretation: the
alpha-zero SU2 smoke is not a zero-lift geometry point, so positive
`CL ~= 0.26` is physically plausible; it still fails the main-wing
`CL > 1.0` lift-acceptance gate at `V=6.5 m/s`.

The main-wing lift-acceptance diagnostic is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-lift-acceptance-diagnostic --out .tmp/runs/main_wing_lift_acceptance_diagnostic
```

This writes `main_wing_lift_acceptance_diagnostic.v1.json` and
`main_wing_lift_acceptance_diagnostic.v1.md`. The current committed result is
`lift_deficit_observed`: the selected OpenVSP-reference 80-iteration smoke
uses `V=6.5 m/s`, `rho=1.225 kg/m^3`, `alpha=0 deg`, and
`REF_AREA=35.175 m^2`, but ends at `CL ~= 0.2632`. At this flow condition,
that corresponds to about `240 N` of normalized lift versus about `910 N` at
the minimum acceptable `CL=1.0`. The report therefore treats the current
solver smoke as below the main-wing lift acceptance gate. This is not a claim
that the aircraft cannot trim; it means the alpha-zero route smoke cannot be
accepted as converged main-wing evidence. Because the VSPAERO panel baseline at
the same nominal `alpha=0 deg`, `V=6.5 m/s` setup is already above the CL gate,
the diagnostic no longer treats alpha-zero alone as a satisfactory explanation.
It now ranks likely next suspects as SU2 force-marker consistency,
boundary-condition consistency, reference-policy consistency, non-convergence,
mesh-quality pathology, and the VSPAERO DegenGeom lifting-surface vs SU2 Euler
wall geometry contract. The reference-area mismatch is kept visible but marked
too small to explain the lift gap by itself.

The main-wing reference-geometry gate is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-reference-geometry-gate --out .tmp/runs/main_wing_reference_geometry_gate
```

This writes `main_wing_reference_geometry_gate.v1.json` and
`main_wing_reference_geometry_gate.v1.md`. The default declared-reference result
is `warn`: the declared `REF_AREA=34.65` and `REF_LENGTH=1.05` imply a 33 m full
span by `ref_area_over_ref_length`, which cross-checks against real geometry
bounds. The 1.05 m reference chord now also cross-checks against OpenVSP/VSPAERO
`cref=1.0425 m` within the pass tolerance. The remaining reference blockers are
the applied-area mismatch (`34.65 m^2` vs OpenVSP/VSPAERO `Sref=35.175 m^2`) and
the quarter-chord moment origin differing from the VSPAERO CG settings.

An OpenVSP-reference variant is committed under
`docs/reports/main_wing_openvsp_reference_geometry_gate/`. It reads the
probe-local OpenVSP-reference SU2 handoff and records `derived_full_span_method`
as `area_provenance.details.wing_quantities.bref`, so span comes from the
OpenVSP/VSPAERO `Bref=33.0 m` provenance instead of assuming `Sref/Cref` is a
span definition. That variant passes the area/chord/span cross-checks and keeps
only the moment-origin policy as `warn`; it is still report-only and does not
change production defaults.

The first route-specific main-wing mesh smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-mesh-handoff-smoke --out .tmp/runs/main_wing_mesh_handoff_smoke
```

This writes `main_wing_mesh_handoff_smoke.v1.json` and
`main_wing_mesh_handoff_smoke.v1.md`. It runs real Gmsh for a synthetic thin
closed-solid wing slab and emits `mesh_handoff.v1` with component-owned
`main_wing` / `farfield` markers. It still does not run BL runtime, does not run SU2, does
not emit `su2_handoff.v1`, does not emit `convergence_gate.v1`, and does not
prove real aerodynamic main-wing geometry.

The first main-wing SU2 handoff materialization smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-su2-handoff-smoke --out .tmp/runs/main_wing_su2_handoff_smoke
```

This writes `main_wing_su2_handoff_smoke.v1.json` and
`main_wing_su2_handoff_smoke.v1.md`. It consumes the synthetic non-BL
main-wing `mesh_handoff.v1` and materializes `su2_handoff.v1`, `mesh.su2`, and
`su2_runtime.cfg` without executing `SU2_CFD`. It consumes the component-owned
`main_wing` wall marker, but remains synthetic wiring evidence. Real main-wing
mesh/SU2/solver status is owned by the real probes above, and convergence still
fails.

The first tail-wing ESP-rebuilt geometry smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-esp-rebuilt-geometry-smoke --out .tmp/runs/tail_wing_esp_rebuilt_geometry_smoke
```

This writes `tail_wing_esp_rebuilt_geometry_smoke.v1.json` and
`tail_wing_esp_rebuilt_geometry_smoke.v1.md`. It consumes
`data/blackcat_004_origin.vsp3`, selects the OpenVSP `Elevator` as
`tail_wing` / `horizontal_tail`, and materializes an ESP-normalized thin
lifting-surface STEP. It still does not run Gmsh, does not emit
`mesh_handoff.v1`, does not run SU2, and does not prove solver credibility.

The first tail-wing mesh handoff smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-mesh-handoff-smoke --out .tmp/runs/tail_wing_mesh_handoff_smoke
```

This writes `tail_wing_mesh_handoff_smoke.v1.json` and
`tail_wing_mesh_handoff_smoke.v1.md`. It runs real Gmsh for a synthetic thin
closed-solid tail slab and emits `mesh_handoff.v1` with component-owned
`tail_wing` / `farfield` markers. It still does not run BL runtime, does not run
SU2, does not emit `su2_handoff.v1`, does not emit `convergence_gate.v1`, and
does not prove real aerodynamic tail geometry.

The first tail-wing SU2 handoff materialization smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-su2-handoff-smoke --out .tmp/runs/tail_wing_su2_handoff_smoke
```

This writes `tail_wing_su2_handoff_smoke.v1.json` and
`tail_wing_su2_handoff_smoke.v1.md`. It consumes the synthetic non-BL
tail-wing `mesh_handoff.v1` and materializes `su2_handoff.v1`, `mesh.su2`, and
`su2_runtime.cfg` without executing `SU2_CFD`. It consumes the component-owned
`tail_wing` wall marker; real tail geometry, solver history, and convergence
remain missing.

The first real tail-wing mesh handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-real-mesh-handoff-probe --out .tmp/runs/tail_wing_real_mesh_handoff_probe
```

This writes `tail_wing_real_mesh_handoff_probe.v1.json` and
`tail_wing_real_mesh_handoff_probe.v1.md`. The current result is
`mesh_handoff_blocked`: real ESP tail geometry is surface-only
(`surface_count=6`, `volume_count=0`), and the existing
`gmsh_thin_sheet_surface` route expects OCC volumes. Synthetic tail slab
evidence must not be treated as real tail mesh handoff evidence.

The real tail surface mesh probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-surface-mesh-probe --out .tmp/runs/tail_wing_surface_mesh_probe
```

This writes `tail_wing_surface_mesh_probe.v1.json` and
`tail_wing_surface_mesh_probe.v1.md`. The current result is
`surface_mesh_pass`: Gmsh can mesh the six real ESP tail surfaces into 2286
surface elements with a `tail_wing` physical group. This is still not
`mesh_handoff.v1`; no farfield volume or SU2-ready external-flow volume exists.

The real tail solidification probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-solidification-probe --out .tmp/runs/tail_wing_solidification_probe
```

This writes `tail_wing_solidification_probe.v1.json` and
`tail_wing_solidification_probe.v1.md`. The current result is
`no_volume_created`: bounded Gmsh heal/sew/makeSolids attempts create 12
surfaces and 0 volumes. The next viable implementation is explicit caps or a
baffle-volume route.

The explicit tail volume route probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-explicit-volume-route-probe --out .tmp/runs/tail_wing_explicit_volume_route_probe
```

This writes `tail_wing_explicit_volume_route_probe.v1.json` and
`tail_wing_explicit_volume_route_probe.v1.md`. The current result is
`explicit_volume_route_blocked`: `occ.addSurfaceLoop(..., sewing=True)` plus
`occ.addVolume(...)` creates one explicit volume candidate, but the signed
volume is negative and the farfield cut is not a valid external-flow boundary.
The baffle-fragment candidate owns a fluid/farfield candidate, but fails 3D
meshing with `tail_baffle_fragment_mesh_failed_plc`. The next viable
implementation is explicit volume orientation repair or baffle-surface
ownership cleanup, not solver execution.

## Formal v1 Capabilities

| Capability | Status | Notes |
| --- | --- | --- |
| `openvsp_surface_intersection` provider | formal `v1` | `.vsp3 -> normalized STEP`, topology report, provider log |
| `GeometryProviderResult` | fixed | formal provider contract |
| `aircraft_assembly` family dispatch | formal `v1` | `thin_sheet_aircraft_assembly` |
| `gmsh_thin_sheet_aircraft_assembly` | formal `v1` | real Gmsh external-flow volume mesh |
| `mesh_handoff.v1` | fixed | downstream mesh contract |
| baseline SU2 materialization | formal `v1` | case generation, solver invocation, history parse |
| `su2_handoff.v1` | fixed | baseline CFD contract |
| `convergence_gate.v1` | fixed | mesh / iterative / overall comparability verdict for the baseline route |
| `mesh_study.v1` | formal minimal `v1` | three-tier coarse / medium / fine baseline study that aggregates per-case gates into one study verdict |
| reference provenance gate | fixed | `geometry_derived`, `baseline_envelope_derived`, `user_declared` |
| force-surface provenance gate | fixed | whole-aircraft wall plus component-owned `fairing_solid` / lifting-surface markers |

## Experimental

| Capability | Status | Why |
| --- | --- | --- |
| `esp_rebuilt` provider | experimental | native OpenCSM rule-loft rebuild 已可 materialize normalized geometry；`main_wing` aircraft-only coarse 2D 已可穿過，但 full external-flow route 的 default sizing 仍卡在 downstream Gmsh meshing |
| `main_wing` | experimental | real ESP/VSP geometry smoke exists for `Main Wing`; bounded real-geometry mesh handoff now writes `mesh_handoff.v1`; real-geometry `su2_handoff.v1` materializes with a `main_wing` force marker and `V=6.5`; a probe-local OpenVSP reference-policy handoff and solver smoke also materialize; force-marker audit passes marker checks with Euler-wall/reference scope warnings; default and OpenVSP-reference 12-iteration solver smokes fail the convergence gate, the OpenVSP-reference 80-iteration probe is also `fail/not_comparable` after CL gating, `surface.csv` and `forces_breakdown.dat` are retained, reference chord now cross-checks against OpenVSP/VSPAERO `cref`; readiness records the OpenVSP-reference geometry gate with span from `Bref=33.0`; lift diagnostic records VSPAERO panel `CLtot=1.2876` vs selected SU2 `CL=0.2632`, while default reference-area and all formal moment-origin policy remain `warn` |
| `tail_wing` | experimental | real ESP/VSP geometry, surface-mesh, naive-solidification, and explicit-volume-route probes exist; real volume mesh handoff is blocked by surface-only provider output, negative signed-volume explicit surface-loop behavior, and baffle-fragment PLC failure; synthetic non-BL `mesh_handoff.v1` / `su2_handoff.v1` smokes exist but are not real tail mesh evidence |
| `fairing_solid` | experimental | real fairing VSP geometry smoke exists for a `best_design` Fuselage with closed-solid topology; bounded real-geometry mesh handoff writes `mesh_handoff.v1` with a `fairing_solid` marker; real-geometry `su2_handoff.v1` materialization exists; external fairing reference policy is now applied in a gated override handoff; borrowed zero moment origin, solver history, and convergence gate are still missing |
| `fairing_vented` | experimental | dispatch exists, real backend not productized |
| direct multi-family package configs | experimental | do not present as formal current route |

If a route returns `route_stage=placeholder`, it is not a formal meshing result.

## ESP Current Reality

- `esp_rebuilt` 已不再是 `not_materialized` stub。`src/hpa_meshing/providers/esp_pipeline.py` 現在走 native OpenCSM lifting-surface rebuild：從 `.vsp3` 讀 wing/tail sections，生成 rule-loft `.csm`，再用 `serveCSM -batch` 輸出 normalized STEP 與 topology artifact。
- 這台 Mac mini（macOS 26.4.1 / arm64）的 runtime truth 已更新：`serveESP` / `serveCSM` 在 `PATH` 上、`ocsm` 仍缺席，但 batch 路徑可以直接用 `serveCSM`。因此 provider 在本機已經 runnable，不再被 `esp_runtime_missing` 擋住。
- 2026-04-30 的 `main_wing_esp_rebuilt_geometry_smoke.v1` 已把主翼 real provider evidence 收進 committed report：`Main Wing` 可被選取並 materialize 成 normalized STEP，topology 為 `1 body / 32 surfaces / 1 volume`；後續 `main_wing_real_mesh_handoff_probe.v1` 已用 coarse bounded sizing 寫出 real `mesh_handoff.v1`，`main_wing_real_su2_handoff_probe.v1` 寫出 real `su2_handoff.v1`，`main_wing_real_solver_smoke_probe.v1` 則留下 solver executed but not converged 的 evidence。
- 2026-04-21 的 provider smoke 已成功 materialize：`hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_native_provider_smoke/` 內有 `normalized.stp` / `topology.json` / `provider_log.json`，且 topology 為 `1 body / 32 surfaces / 1 volume`、`duplicate_interface_face_pair_count = 0`。
- 2026-04-21 晚上的 C1 diagnostics 已把「有 hang」收斂成更精確的證據：`hpa_meshing_package/.tmp/runs/codex_c1_mesh2d_forensics_20260421/` 內的 `main_wing` full-route A/B 顯示 `Mesh.Algorithm = 1 / 5 / 6` 在 default sizing 下都會 timeout；default case 的 watchdog 會穩定卡在 `surface 14 (BSpline surface)`，coarse route 則能穿過 aircraft surfaces、把最後 surface 記到 `surface 33 (Plane)`，表示 farfield 會放大下游成本。
- 同一輪 `surface_patch_diagnostics.json` 也留下了可疑 patch family：`surface 31/32` 與 `surface 5/6/1/10` 持續被排在最前面，特徵是 `short_curve_candidate + high_aspect_strip_candidate`，位置落在翼外段 span-extreme strip 與 root / trailing-edge 附近的小 strip faces。
- 更重要的是，`hpa_meshing_package/.tmp/runs/codex_c1_surface_only_forensics_scaled_20260421/` 已證明 native `main_wing` 本體不是完全不能做 2D：aircraft-only、properly scaled、`global_min_size=0.05` 的 coarse005 probe 可以在 `2.83 s` 內完成 `surface_mesh_2d.msh`，`35770 nodes / 74077 elements`；但相同 aircraft-only probe 在 default sizing 下仍會於 `surface 14` 附近 timeout。
- 結論：`esp_rebuilt` 目前仍是 experimental，但已經從「provider runnable」再往前推到「可診斷的 meshing route」。最小 blocker 不再是 provider topology，而是 native loft patches 在 default/ref-length sizing 下進入不穩定的 Gmsh 2D meshing regime；assembly 則在此之上再疊加 farfield / 1D memory 壓力。
- 具體實作規劃請看 [docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md](../../docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md)。

## Explicit Non-Goals For This Round

- claiming final high-quality CFD credibility
- alpha sweep
- component-level force mapping
- making ESP/OpenCSM a hard runtime dependency

## Planned Next Gates

1. Alpha sweep only after `mesh_study.v1` promotes the chosen baseline mesh/runtime to at least `preliminary_compare`
2. Run a side-aware STEP / BREP / EGADS format-boundary probe, or add an owned OCC export path, before any mesh handoff or solver-budget work
3. Use retained main-wing `forces_breakdown.dat` / `surface.csv` to debug the panel-vs-SU2 lift gap, then fix reference-area / moment-origin provenance before any larger residual/numerics campaign; do not call either smoke converged
4. Run real fairing solver smoke now that drag/reference normalization is explicit; keep moment coefficients blocked until moment-origin policy is owned
5. Tail-wing `su2_handoff.v1` materialization smoke before tail solver claims
6. Component-level force mapping after the wall-marker story is stronger

## What A New Contributor Should Assume

- Start from the package root, not from old worktree memory
- Treat the provider-aware `aircraft_assembly` route as source of truth
- Treat `status=success` and `overall_convergence_gate` as separate signals: success means it ran, the gate says whether it is comparable
- Treat `mesh_study.v1` as the promotion gate before any alpha sweep work: if it says `still_run_only` or `insufficient`, do not pretend the baseline is ready to compare
- Treat everything else as scaffolding until it is promoted with a real backend and smoke evidence
