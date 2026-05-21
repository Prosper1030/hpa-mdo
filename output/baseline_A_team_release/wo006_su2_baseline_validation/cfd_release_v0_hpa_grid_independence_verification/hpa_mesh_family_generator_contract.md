# HPA Mesh Family Generator Contract

Verdict: `implemented_as_family_gate_not_single_fine_patch`

The WO-006 OpenFOAM grid workflow now treats Coarse / Medium / Fine as one
mesh family. A single Fine failure is not a special case and does not unlock
solver execution.

## Generator Contract

- same geometry, AoA, rho, V, viscosity, turbulence model, BCs, force
  definitions, reference area, and reference length on every rung
- same swept open-TE C-grid topology on every rung
- same seven local refinement regions on every rung:
  `leading_edge`, `trailing_edge`, `boundary_layer`, `near_wake`,
  `downstream_wake`, `wing_tip_vortex_region`, `farfield`
- same spacing-rule keys on every region:
  `surface_spacing_m`, `first_layer_height_m`, `bl_growth_rate`,
  `bl_layer_count`, `wake_streamwise_spacing_m`,
  `tip_refinement_radius_m`, `farfield_distance_chords`
- same generator-level quality guards:
  no open cells, no negative volumes, no wrong-oriented face pyramids,
  no TE sliver faces, no body/wake non-planar sliver interface,
  max skew threshold, max non-orthogonality threshold, y+ target support

## Family Gate

The workflow performs a mesh-only pass first. It starts OpenFOAM solver runs
only if every requested rung is strict `checkMesh -meshQuality` clean.

Current run:

```text
coarse: strict_checkMesh_clean = false
medium: strict_checkMesh_clean = false
fine:   strict_checkMesh_clean = false
```

Therefore the solver phase is blocked. No CD, CL, Cm, Cp, Cf, wake, or
tip-vortex convergence claim can be made from this family yet.

## Current Engineering Blocker

The old high-resolution TE open-cell problem and the later `100`
wrong-oriented lower-TE face-pyramid problem are not the active blockers.
The active blocker is the inherited determinant/twist meshQuality failure
across the C/M/F family, plus the lack of stable force histories after a
strict-clean family is available.
