# WO-006 CFD External Rescue Reference

Date: 2026-05-14

This note preserves the user-supplied GPT Pro engineering direction for the
WO-006 CFD rescue. It is not the active route authority. The active authority is
still `cfd_release_v0/manifest.yaml`; use this note only as external engineering
guidance when a named gate fails or when deciding whether a proposed workaround
is drifting back into the retired R-series patch loop.

## Boundary

- Treat WO-006R27/R28/R29/R30 as forensic evidence, not active CFD delivery.
- Do not open R31/R32-style local patch work unless
  `canonical_hybrid_halfwing_v0` fails a named manifest gate and the proposed
  work directly addresses that gate.
- R30 is a route kill condition for the old custom handoff: the SU2-style
  subvolume hotspot matched the R28 magnitude and localized to the farfield /
  `core_tet_mesh` region, not to a simple wall marker omission.
- SU2 is not rejected as a solver; the rejected part is the custom all-tet /
  global-star / owner-pyramid / closure-repair mesh handoff.

## Precedent Pattern

Adjacent CFD precedents point to the same workflow shape:

- HPA and low-Re airfoil design needs a 2D section envelope before trusting any
  3D RANS drag number.
- Low-Re 2D airfoil CFD is feasible, but only with careful near-wall mesh,
  wall treatment, and force stability checks.
- Finite-wing cases are sensitive to tip, cap, farfield, and force integration;
  a bad cap or polluted marker can dominate CD.
- SU2 can run wing RANS when the mesh, markers, reference quantities, and
  boundary conditions are coherent.
- Successful external-aero mesh routes use prism/hexa boundary-layer cells and
  a tetra or hybrid core with a clean conformal interface; they do not split the
  BL into global-star all-tet cells.

These are directional references, not literature citations. Verify primary
sources before using any of them as publishable evidence.

## Practical Use

When stuck, route the failure through this sequence instead of adding local
repairs to the retired mesh:

1. Retire the R27/R28/R29/R30 route from active delivery.
2. Rebuild clean half-wing farfield/core topology; avoid farfield pole/fan
   vertices and gate excessive incident-cell count at farfield vertices.
3. Pass SU2-style dual/control-volume quality before solver work.
4. Split markers into `wing_upper`, `wing_lower`, `tip_wall`, `te_wall`,
   `closure_wall`, `root_symmetry`, and `farfield`.
5. Run pressure-only half-wing sanity before any viscous BL claim.
6. Build a true hybrid BL mesh that preserves prism/hexa BL cells and tetra
   core cells.
7. Run wall-resolved `INC_RANS/SA` at `AOA=0` when geometry carries incidence,
   with wing-only force monitoring and closure forces reported separately.
8. Only after route-smoke passes, run the coarse/medium/fine grid ladder from
   the same generator and marker policy.

## Tool Choice Guidance

- Primary route: SU2 plus clean hybrid half-wing mesh.
- Cross-check route: OpenFOAM can be useful for pressure/viscous sanity if SU2
  remains blocked by vertex-centered dual metrics.
- Commercial meshing is optional, not required, but may reduce the largest
  current risk: robust hybrid BL/farfield mesh generation.
- Gmsh is acceptable only when it owns a coherent mesh/export path or when a
  converter preserves cell types without topology repair.

## Engineering Guardrails

- Conservative numerics can diagnose; they cannot set a pass status.
- Primal positive volume and marker audit are necessary but not sufficient.
- Closure and tip forces must stay separate until their CD contribution is
  proved small or physically explainable.
- A 2D XFOIL/NeuralFoil/polar envelope is a sanity boundary, not a substitute
  for 3D CFD.
- `CD <= 0.15` is only a route-smoke rejection gate. A credible HPA main-wing
  result should eventually return to a `0.0XX` drag order and pass grid-ladder
  checks.
