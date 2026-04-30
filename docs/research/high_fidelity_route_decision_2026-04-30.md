# High-Fidelity Route Decision (2026-04-30)

## Decision

The high-fidelity automation mainline must move from a single `shell_v4` fixture
repair loop to a component-family route architecture.

The long-term target is:

```text
VSP / ESP geometry
  -> component-family classification
  -> route selection
  -> meshability gates
  -> Gmsh mesh handoff
  -> SU2 baseline / convergence reporting
```

for arbitrary human-powered-aircraft:

- main wing
- tail wing / horizontal tail / vertical tail
- fairing solid / vented fairing

`shell_v4` remains valuable, but its role is now diagnostic and promotional:
it can prove whether a boundary-layer route has enough owned topology to be
promoted. It must not be treated as the product route just because one hard
fixture becomes greener.

## Why This Decision Exists

The `shell_v1 -> shell_v4` history is still useful:

- `shell_v1` proved the route could reach a rough 3D volume smoke.
- `shell_v2` compressed the worst tip family into a smaller residual set.
- `shell_v3` moved the root cause upstream and produced a frozen geometry /
  coarse-CFD reference.
- `shell_v4` correctly opened a real boundary-layer / solver-validation branch.

That progression was not wasted effort. The problem is that the active
`root_last3` work has crossed from route hardening into narrow topology
microscopy. The evidence pattern is no longer a clean monotonic improvement:
`failed_steiner`, `segment_facet_intersection`, `loop_not_closed`, inferred
sleeve ownership, and missing or inferred BL-to-core handoff ownership all
point to the same architecture boundary.

The missing object is not another surface-id patch. The missing product
capability is an hpa-mdo-owned handoff topology that Gmsh only consumes after
hpa-mdo has already guaranteed the boundary.

## Product-Line Rule

Do not promote a component family by making one `shell_v4` fixture pass.

Promote a component family only when the route has:

1. provider materialization or a formal direct-CAD source
2. geometry-family classification
3. route-specific mesh smoke
4. `mesh_handoff.v1`
5. `su2_handoff.v1`
6. `convergence_gate.v1`
7. for BL routes only: owned transition sleeve / interface-loop handoff

This keeps "it ran" separate from "it is comparable", and keeps "diagnostic
evidence improved" separate from "this is a productized route".

## Component-Family Readiness

The machine-readable readiness surface is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli route-readiness \
  --out .tmp/runs/component_family_route_readiness
```

It writes:

- `component_family_route_readiness.v1.json`
- `component_family_route_readiness.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/component_family_route_readiness.v1.json`
- `hpa_meshing_package/docs/reports/component_family_route_readiness.v1.md`

The companion pre-mesh dispatch smoke matrix is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli component-family-smoke-matrix \
  --out .tmp/runs/component_family_route_smoke_matrix
```

It writes:

- `component_family_route_smoke_matrix.v1.json`
- `component_family_route_smoke_matrix.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/component_family_route_smoke_matrix.v1.json`
- `hpa_meshing_package/docs/reports/component_family_route_smoke_matrix.v1.md`

This smoke matrix is not a mesh pass. It only proves that main-wing, tail, and
fairing route skeletons are visible, classified, and dispatched outside
`root_last3`.

The first real fairing geometry smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-geometry-smoke \
  --out .tmp/runs/fairing_solid_real_geometry_smoke
```

It writes:

- `fairing_solid_real_geometry_smoke.v1.json`
- `fairing_solid_real_geometry_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/fairing_solid_real_geometry_smoke/fairing_solid_real_geometry_smoke.v1.json`
- `hpa_meshing_package/docs/reports/fairing_solid_real_geometry_smoke/fairing_solid_real_geometry_smoke.v1.md`

Observed result:

- `geometry_smoke_status = geometry_smoke_pass`
- selected VSP geometry: `best_design` / `Fuselage`
- topology: `1 body / 8 surfaces / 1 volume`
- Gmsh meshing, SU2, BL runtime, and convergence are not run

Engineering reading: this geometry smoke originally moved fairing away from
"real geometry missing". The later fairing real mesh/SU2 probes now own the
downstream route status. The synthetic closed-solid box mesh and SU2 handoff
remain useful route-materialization evidence, but they are not substitutes for
real fairing route evidence.

The first real fairing mesh handoff probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-mesh-handoff-probe \
  --out .tmp/runs/fairing_solid_real_mesh_handoff_probe
```

It writes:

- `fairing_solid_real_mesh_handoff_probe.v1.json`
- `fairing_solid_real_mesh_handoff_probe.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/fairing_solid_real_mesh_handoff_probe/fairing_solid_real_mesh_handoff_probe.v1.json`
- `hpa_meshing_package/docs/reports/fairing_solid_real_mesh_handoff_probe/fairing_solid_real_mesh_handoff_probe.v1.md`

Observed result:

- `probe_status = mesh_handoff_pass`
- `mesh_handoff_status = written`
- markers: `fairing_solid` and `farfield`
- mesh scale: about `29k nodes / 173k elements`
- backend unit rescale applied: `import_scale_to_units ~= 0.001`
- SU2, BL runtime, and convergence are not run

Engineering reading: fairing is now the cleanest component-family branch after
the formal aircraft assembly. It has now earned a real SU2 handoff
materialization probe; the next fairing question is reference-quantity
credibility before any coefficient or convergence claim.

The first real fairing SU2 handoff probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-su2-handoff-probe \
  --out .tmp/runs/fairing_solid_real_su2_handoff_probe \
  --source-mesh-probe-report docs/reports/fairing_solid_real_mesh_handoff_probe/fairing_solid_real_mesh_handoff_probe.v1.json
```

It writes:

- `fairing_solid_real_su2_handoff_probe.v1.json`
- `fairing_solid_real_su2_handoff_probe.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/fairing_solid_real_su2_handoff_probe/fairing_solid_real_su2_handoff_probe.v1.json`
- `hpa_meshing_package/docs/reports/fairing_solid_real_su2_handoff_probe/fairing_solid_real_su2_handoff_probe.v1.md`

Observed result:

- `materialization_status = su2_handoff_written`
- `source_mesh_handoff_status = written`
- `wall_marker_status = fairing_solid_marker_present`
- `force_surface_scope = component_subset`
- `reference_geometry_status = warn`
- `SU2_CFD` and convergence are not run

Engineering reading: fairing has crossed provider, real Gmsh mesh handoff, and
real SU2 handoff materialization. It is still not a credible CFD product line:
the current reference quantities come from available fairing provider metadata
with warning status, no solver history exists, and `convergence_gate.v1` is
absent.

The neighboring fairing project is useful reference-policy evidence. The first
report-only probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-reference-policy-probe \
  --out .tmp/runs/fairing_solid_reference_policy_probe
```

Observed result:

- `reference_policy_status = reference_mismatch_observed`
- external fairing policy: `REF_AREA=1.0`, `REF_LENGTH=2.82880659`, `V=6.5`
- legacy pre-standard hpa-mdo real fairing handoff artifact: `REF_AREA=100`, `REF_LENGTH=1`, `V=10`
- marker mapping needed: external `fairing` -> hpa-mdo `fairing_solid`
- no runtime apply, no Gmsh, no `SU2_CFD`, no convergence

Engineering reading: this explains the current `reference_geometry_status=warn`
as a concrete policy mismatch rather than a vague provider concern. The next
fairing step should be an explicit approved reference override, not a solver run
with the wrong coefficient normalization. `V=10` is not the HPA operating
standard; package-native SU2 defaults and editable `su2.flow_conditions` now use
`V=6.5`.

That reference override now exists as a gated materialization probe:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-reference-override-su2-handoff-probe \
  --out .tmp/runs/fairing_solid_reference_override_su2_handoff_probe
```

Observed result:

- `materialization_status = su2_handoff_written`
- `reference_override_status = applied_with_moment_origin_warning`
- applied fairing policy: `REF_AREA=1.0`, `REF_LENGTH=2.82880659`, `V=6.5`
- `MARKER_MONITORING = fairing_solid`
- `solver_execution_status = not_run`
- `convergence_gate_status = not_run`

Engineering reading: drag/reference normalization is now explicit enough for a
bounded solver smoke. It is still not enough for moment coefficients because the
moment origin is borrowed zero-origin evidence and remains a blocker.

The synthetic closed-solid route-specific Gmsh smoke selected from that matrix is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-mesh-handoff-smoke \
  --out .tmp/runs/fairing_solid_mesh_handoff_smoke
```

It writes:

- `fairing_solid_mesh_handoff_smoke.v1.json`
- `fairing_solid_mesh_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/fairing_solid_mesh_handoff_smoke/fairing_solid_mesh_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/fairing_solid_mesh_handoff_smoke/fairing_solid_mesh_handoff_smoke.v1.md`

This smoke emits a real `mesh_handoff.v1` for `fairing_solid ->
gmsh_closed_solid_volume`. It now includes a component-specific `fairing_solid`
force marker in the mesh-handoff evidence. The SU2 backend can materialize a
`su2_handoff.v1` from that marker without running `SU2_CFD`, but the committed
route evidence is still not a solver route and `convergence_gate.v1` is
intentionally absent.

The first fairing SU2 handoff materialization smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-su2-handoff-smoke \
  --out .tmp/runs/fairing_solid_su2_handoff_smoke
```

It writes:

- `fairing_solid_su2_handoff_smoke.v1.json`
- `fairing_solid_su2_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/fairing_solid_su2_handoff_smoke/fairing_solid_su2_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/fairing_solid_su2_handoff_smoke/fairing_solid_su2_handoff_smoke.v1.md`

This smoke emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without
running `SU2_CFD`. It consumes the component-owned `fairing_solid` wall marker
and reports `force_surface_scope=component_subset`. It deliberately keeps the
remaining engineering blockers visible: the geometry is still synthetic, solver
history is absent, and convergence has not been evaluated.

The first real main-wing ESP-rebuilt geometry smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-esp-rebuilt-geometry-smoke \
  --out .tmp/runs/main_wing_esp_rebuilt_geometry_smoke
```

It writes:

- `main_wing_esp_rebuilt_geometry_smoke.v1.json`
- `main_wing_esp_rebuilt_geometry_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/main_wing_esp_rebuilt_geometry_smoke/main_wing_esp_rebuilt_geometry_smoke.v1.json`
- `hpa_meshing_package/docs/reports/main_wing_esp_rebuilt_geometry_smoke/main_wing_esp_rebuilt_geometry_smoke.v1.md`

Observed result:

- `geometry_smoke_status = geometry_smoke_pass`
- selected VSP geometry: `Main Wing`
- topology: `1 body / 32 surfaces / 1 volume`
- Gmsh, SU2, BL runtime, and convergence are not run

Engineering reading: this geometry smoke originally moved the blocker away from
"real geometry missing". The later real mesh/SU2/solver probes now own the
downstream route status. The synthetic slab mesh and SU2 handoff remain useful
marker/materialization evidence, but they are not substitutes for real
ESP/VSP-main-wing route evidence.

The first real main-wing mesh handoff probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-real-mesh-handoff-probe \
  --out .tmp/runs/main_wing_real_mesh_handoff_probe
```

It writes:

- `main_wing_real_mesh_handoff_probe.v1.json`
- `main_wing_real_mesh_handoff_probe.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.json`
- `hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.md`

Observed result:

- `probe_status = mesh_handoff_pass`
- `mesh_handoff_status = written`
- provider geometry has `surface_count = 32`, `volume_count = 1`
- markers: `main_wing`, `farfield`, and `fluid`
- mesh scale: `97299 nodes`, `584460 volume elements`
- 3D watchdog: `completed_without_timeout`

Engineering reading: this moves the real main-wing route past the previous
volume-insertion blocker. It is still a coarse bounded probe, not production
default sizing and not a BL route, but the route now has a real
`mesh_handoff.v1` artifact that downstream SU2 probes can consume.

The first real main-wing SU2 handoff probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-real-su2-handoff-probe \
  --out .tmp/runs/main_wing_real_su2_handoff_probe \
  --source-mesh-probe-report docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.json
```

Observed result:

- `materialization_status = su2_handoff_written`
- force marker: component-owned `main_wing`
- `REF_AREA = 34.65`, `REF_LENGTH = 1.05`
- flow condition: `V = 6.5 m/s`
- solver and convergence are not run
- `reference_geometry_status = warn`

Engineering reading: materialized SU2 handoff is not CFD-ready by itself. It
proves marker and runtime wiring from the real mesh, while keeping reference
provenance and solver convergence as separate gates.

The first real main-wing solver smoke probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-real-solver-smoke-probe \
  --out .tmp/runs/main_wing_real_solver_smoke_probe \
  --source-su2-probe-report docs/reports/main_wing_real_su2_handoff_probe/main_wing_real_su2_handoff_probe.v1.json \
  --timeout-seconds 180
```

Observed result:

- `solver_execution_status = solver_executed`
- `run_status = solver_executed_but_not_converged`
- `final_iteration = 11`
- final coefficients from the smoke history: `CL ~= 0.2642`, `CD ~= 0.01887`
- `convergence_gate_status = fail`
- `comparability_level = not_comparable`

Engineering reading: the solver executed and wrote history, but the result is
not converged. The SU2 log itself reports max iterations reached before
convergence; the gate also shows residual drop below threshold, coefficient
tails still drifting, and reference gate warning.

A non-default 40-iteration follow-up smoke is kept at:

- `hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe_iter40/main_wing_real_solver_smoke_probe.v1.json`
- `hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe_iter40/artifacts/convergence_gate.v1.json`

Observed result:

- `runtime_max_iterations = 40`
- `solver_execution_status = solver_executed`
- `run_status = solver_executed_but_not_converged`
- `convergence_gate_status = warn`
- `convergence_comparability_level = run_only`
- `final_iteration = 39`
- final coefficients from the smoke history: `CL ~= 0.2719`, `CD ~= 0.0260`

Engineering reading: the longer budget helps. Coefficient stability reaches
`pass`, but residual trend is still below threshold and the reference gate is
still `warn`. This is useful blocker evidence, not converged CFD.

The main-wing reference-geometry gate is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-reference-geometry-gate \
  --out .tmp/runs/main_wing_reference_geometry_gate
```

Observed result:

- `reference_gate_status = warn`
- declared full span from `REF_AREA / REF_LENGTH` is `33.0 m`
- real geometry bounds span is `33.0 m`
- selected OpenVSP span cross-check is `32.9493 m`
- reference chord now cross-checks against OpenVSP/VSPAERO `cref=1.0425 m`
- applied `REF_AREA=34.65` differs from OpenVSP/VSPAERO `Sref=35.175` by about 1.49%
- quarter-chord moment origin differs from the VSPAERO CG settings

Engineering reading: reference geometry is no longer opaque, but it is not a
pass gate. The next credibility work should own reference-area and moment-origin
provenance before treating a longer solver campaign as comparable CFD.

A probe-local OpenVSP/VSPAERO reference-policy SU2 handoff snapshot now exists
at:

- `hpa_meshing_package/docs/reports/main_wing_openvsp_reference_su2_handoff_probe/`

Observed result:

- `materialization_status = su2_handoff_written`
- `reference_policy = openvsp_geometry_derived`
- `REF_AREA = 35.175`
- `REF_LENGTH = 1.0425`
- `REF_ORIGIN_MOMENT = (0,0,0)`
- `V = 6.5 m/s`
- force marker = `main_wing`

Engineering reading: this removes ambiguity about whether the real handoff can
consume OpenVSP reference quantities. It is still not a solver or convergence
claim, and the zero VSPAERO CG moment origin keeps the reference state at
`warn`.

The matching non-BL main-wing mesh smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-mesh-handoff-smoke \
  --out .tmp/runs/main_wing_mesh_handoff_smoke
```

It writes:

- `main_wing_mesh_handoff_smoke.v1.json`
- `main_wing_mesh_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/main_wing_mesh_handoff_smoke/main_wing_mesh_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/main_wing_mesh_handoff_smoke/main_wing_mesh_handoff_smoke.v1.md`

This smoke emits a real `mesh_handoff.v1` for `main_wing ->
gmsh_thin_sheet_surface` on a synthetic thin closed-solid wing slab with
component-owned `main_wing` / `farfield` markers. It is not a BL route, not real
aerodynamic wing geometry, not a solver handoff, and not a convergence claim.
Its engineering value is narrower but important: the main-wing family now has a
real package-native mesh-handoff artifact outside `root_last3`, and the marker
scope no longer collapses to whole-aircraft force accounting.

The first main-wing SU2 handoff materialization smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-su2-handoff-smoke \
  --out .tmp/runs/main_wing_su2_handoff_smoke
```

It writes:

- `main_wing_su2_handoff_smoke.v1.json`
- `main_wing_su2_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/main_wing_su2_handoff_smoke/main_wing_su2_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/main_wing_su2_handoff_smoke/main_wing_su2_handoff_smoke.v1.md`

This smoke emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without
running `SU2_CFD`. It now consumes the component-owned `main_wing` wall marker
and reports `force_surface_scope=component_subset`. It deliberately keeps the
remaining engineering blockers visible: the geometry is still synthetic, solver
history is absent, and convergence has not been evaluated.

The first tail-wing mesh handoff smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-mesh-handoff-smoke \
  --out .tmp/runs/tail_wing_mesh_handoff_smoke
```

It writes:

- `tail_wing_mesh_handoff_smoke.v1.json`
- `tail_wing_mesh_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/tail_wing_mesh_handoff_smoke/tail_wing_mesh_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/tail_wing_mesh_handoff_smoke/tail_wing_mesh_handoff_smoke.v1.md`

This smoke emits a real `mesh_handoff.v1` for `tail_wing ->
gmsh_thin_sheet_surface` on a synthetic thin closed-solid tail slab with
component-owned `tail_wing` / `farfield` markers. It is not real tail geometry,
not a solver handoff, and not a convergence claim. Its value is that the tail
family now has one concrete owned-marker mesh-handoff artifact outside the
schema-only route matrix.

The first tail-wing SU2 handoff materialization smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-su2-handoff-smoke \
  --out .tmp/runs/tail_wing_su2_handoff_smoke
```

It writes:

- `tail_wing_su2_handoff_smoke.v1.json`
- `tail_wing_su2_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/tail_wing_su2_handoff_smoke/tail_wing_su2_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/tail_wing_su2_handoff_smoke/tail_wing_su2_handoff_smoke.v1.md`

This smoke consumes the synthetic tail-wing `mesh_handoff.v1` and materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without running `SU2_CFD`.
It owns the `tail_wing` force marker for this synthetic fixture, but it still
does not prove real tail geometry, solver history, or convergence.

The first real tail-wing ESP-rebuilt geometry smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-esp-rebuilt-geometry-smoke \
  --out .tmp/runs/tail_wing_esp_rebuilt_geometry_smoke
```

It writes:

- `tail_wing_esp_rebuilt_geometry_smoke.v1.json`
- `tail_wing_esp_rebuilt_geometry_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/tail_wing_esp_rebuilt_geometry_smoke/tail_wing_esp_rebuilt_geometry_smoke.v1.json`
- `hpa_meshing_package/docs/reports/tail_wing_esp_rebuilt_geometry_smoke/tail_wing_esp_rebuilt_geometry_smoke.v1.md`

This smoke consumes `data/blackcat_004_origin.vsp3`, selects the OpenVSP
`Elevator` as `tail_wing` / `horizontal_tail`, and materializes a normalized
STEP through `esp_rebuilt`. It does not run Gmsh or SU2. The next tail blocker
is now a real-geometry mesh handoff, not provider geometry availability.

The first real tail-wing mesh handoff probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-real-mesh-handoff-probe \
  --out .tmp/runs/tail_wing_real_mesh_handoff_probe
```

It writes:

- `tail_wing_real_mesh_handoff_probe.v1.json`
- `tail_wing_real_mesh_handoff_probe.v1.md`

Observed result:

- `probe_status = mesh_handoff_blocked`
- provider geometry has `surface_count = 6`, `volume_count = 0`
- Gmsh route error: `normalized STEP did not import any OCC volumes for gmsh_thin_sheet_surface`

Engineering reading: the synthetic closed-solid tail slab route is not
representative of real ESP tail geometry.

The surface-only follow-up probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-surface-mesh-probe \
  --out .tmp/runs/tail_wing_surface_mesh_probe
```

Observed result:

- `probe_status = surface_mesh_pass`
- imported surface count: 6
- surface element count: 2286
- volume element count: 0
- `mesh_handoff.v1` is not emitted

Engineering reading: surface-only meshing is useful evidence that the ESP tail
surfaces and `tail_wing` marker can be owned, but it is not SU2-ready. The next
real route decision is provider-side solidification/capping versus a
baffle-volume route.

The naive solidification probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-solidification-probe \
  --out .tmp/runs/tail_wing_solidification_probe
```

Observed result:

- `solidification_status = no_volume_created`
- provider surface count: 6
- best output surface count: 12
- best output volume count: 0
- recommended next: `explicit_caps_or_baffle_volume_route_required`

Engineering reading: naive Gmsh heal/sew/makeSolids is not the next serious
path. The next route should construct explicit caps or a baffle-volume topology.

The explicit volume route probe is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-explicit-volume-route-probe \
  --out .tmp/runs/tail_wing_explicit_volume_route_probe
```

Observed result:

- `route_probe_status = explicit_volume_route_blocked`
- `surface_loop_volume_status = volume_created`
- `surface_loop_signed_volume = -0.03945880563457954`
- `surface_loop_farfield_cut_status = invalid_fluid_boundary`
- `baffle_fragment_status = mesh_failed_plc`
- `mesh_handoff_status = not_written`

Engineering reading: the real tail has now moved past "maybe Gmsh cannot see a
volume" into a more specific route blocker. `occ.addSurfaceLoop` can create an
explicit volume candidate, but the candidate is not a valid external-flow body
until orientation / signed-volume behavior is fixed. The baffle route can own a
farfield fluid candidate, but hpa-mdo still needs to own or de-duplicate the
baffle wall topology before asking Gmsh to tetrahedralize it.

The current expected strategic reading is:

| Component family | Current role | Productized? | Next useful promotion gate |
| --- | --- | --- | --- |
| `aircraft_assembly` | current product line | yes, formal `v1` | mesh-study / convergence promotion |
| `main_wing` | experimental + diagnostic | no | own reference-area / moment-origin provenance, then continue residual/numerics work beyond the current 40-iteration `warn/run_only` smoke |
| `tail_wing` / `horizontal_tail` / `vertical_tail` | registered future route | no | explicit volume orientation repair or baffle-surface ownership, then real volume mesh/SU2 smoke |
| `fairing_solid` | registered future route | no | bounded solver/convergence smoke; moment-origin policy before moment coefficients |
| `fairing_vented` | registered future route | no | perforation ownership and marker contract |

## Boundary-Layer Promotion Policy

The BL route is not abandoned, but it becomes promotion-only.

A BL route can ask Gmsh to do only core tetrahedralization when hpa-mdo already
owns:

- transition sleeve object
- transition rings
- receiver faces
- interface loops
- layer-drop event mapping
- BL-to-core handoff boundary

If any of those are inferred or missing, the correct result is still a handoff
insufficiency. Inferred sleeve ownership cannot pass because it still asks Gmsh
to recover boundary topology that hpa-mdo has not actually defined.

## Gmsh Source Policy

`/Volumes/Samsung SSD/external-src/gmsh` and the previous forensic worktree are
useful for understanding Gmsh boundary recovery. They are not the primary
product-repair path.

Use Gmsh source for:

- forensic instrumentation
- throw-site localization
- minimal repro construction
- distinguishing hpa-mdo topology debt from a true Gmsh bug

Do not use a Gmsh fork as the default answer. A fork is only justified after a
reproducible, cross-fixture Gmsh bug remains after hpa-mdo owns the handoff
topology.

## New Agent Operating Rules

Every future high-fidelity task should answer these before editing code:

1. Which pipeline layer does this advance?
2. Does it help arbitrary main-wing / tail / fairing automation?
3. Is this a product route, diagnostic route, or research branch?
4. What evidence promotes it, and what evidence stops it?

If a task cannot answer those questions, it should not become a repair loop.

## Next Two Tasks

1. Run a bounded real fairing solver smoke now that drag/reference normalization
   is explicit; keep moment coefficients blocked until moment-origin policy is
   owned.
2. Own main-wing reference-area / moment-origin provenance, then continue
   residual/numerics work beyond the current 40-iteration `warn/run_only`
   smoke; keep both current solver smokes labeled
   `solver_executed_but_not_converged`.
