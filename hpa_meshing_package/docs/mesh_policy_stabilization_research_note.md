# Mesh Policy Stabilization Research Note

Date: 2026-04-21
Scope: `hpa_meshing_package` thin-sheet aircraft assembly baseline mesh-study stabilization

## Official doc takeaways

1. Gmsh says general mesh size fields and embedded-model workflows are supported in 3D by `Delaunay` and `HXT`, and calls `Delaunay` the most robust 3D algorithm. For 2D, the manual explicitly says `Delaunay` handles complex mesh size fields and large size gradients better than the default `Frontal-Delaunay`.
2. Gmsh also says that when element sizes are fully prescribed by a background mesh field, it is often desirable to set `Mesh.MeshSizeFromPoints = 0`, `Mesh.MeshSizeFromCurvature = 0`, and `Mesh.MeshSizeExtendFromBoundary = 0` to avoid over-refinement leaking from boundaries into surfaces or volumes.
3. For OpenCASCADE workflows, the official route for mixed-dimension boolean work is `BooleanFragments`, lower-dimensional entities are automatically embedded when needed, and `HealShapes` is the official cleanup path for degenerated edges/faces, small faces, sewing, and solid making.
4. In SU2, `MARKER_FAR` is driven by the free-stream definition, and `AOA` directly changes the free-stream direction. The repo's own `current_status.md` and `mesh_study.v1` / `convergence_gate.v1` contracts therefore match the official sequencing: stabilize the alpha=0 baseline mesh and its iterative comparability first, then consider alpha sweep.

## Answers to the research questions

### 1. Most likely Gmsh branch-sensitivity sources here

- Background `Distance` / `Threshold` fields fighting with default point-curvature-boundary size sources.
- Default 2D `Frontal-Delaunay` reacting differently to large size gradients on thin-sheet boundary surfaces.
- Thin-sheet OCC boolean topology leaving small/degenerated faces or duplicate seams that make later surface recovery fragile.
- Silent meshing-path differences between presets when refinement neighborhoods are not actually tied to requested near-body sizes.

### 2. Is the coarse / medium / fine ladder itself violating common Gmsh guidance?

Not by itself. The more serious issue is that the declared near-body / farfield ladder is not the only size driver unless the extra Gmsh size sources are disabled. In other words, the preset ladder can look reasonable on paper while the real mesh still follows hidden boundary and curvature refinement.

### 3. What is `PLC Error: A segment and a facet intersect at point` most likely telling us here?

Most likely this is not an SU2 problem and not a reference-data problem. In this route it points to invalid or inconsistent boundary recovery during Gmsh tetrahedralization: overlapping / self-intersecting surface facets, duplicated thin-sheet faces, or OCC fragment topology that did not cleanly heal before 3D meshing.

### 4. From the SU2 / CFD side, what should stabilize before alpha sweep?

The alpha=0 package-native baseline must first produce:

- stable `mesh_handoff.v1` markers and fluid volume
- per-case `convergence_gate.v1` iterative stability on `history.csv`
- a `mesh_study.v1` result that at least reaches `preliminary_compare`

Without that, changing `AOA` just moves the freestream direction on top of an already branch-sensitive mesh route.

## Minimal fix to apply this round

1. Keep the experimental OCC-healing plus preset-scaled transition band, because it already improves the medium/fine cases and moves the problem away from pure solver runtime.
2. Make the mesh policy deterministic and field-driven in the Gmsh backend:
   - explicitly disable `Mesh.MeshSizeFromPoints`
   - explicitly disable `Mesh.MeshSizeFromCurvature`
   - explicitly disable `Mesh.MeshSizeExtendFromBoundary`
   - explicitly use 2D `Delaunay` for the field-driven thin-sheet route
   - explicitly record the chosen mesh-policy settings in metadata / tests

## Expected outcome

This should not be described as a guaranteed one-patch path to `preliminary_compare`. The honest goal is narrower: reduce policy-induced branch sensitivity, keep the thin-sheet route on one clearer meshing architecture, and see whether the real study tightens enough to promote the baseline.
