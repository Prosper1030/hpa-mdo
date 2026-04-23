# topology_ir.v1

`topology_ir.v1` is the first topology-first intermediate representation for the `esp_rebuilt -> shell_v4` meshing line.

## Purpose

This contract does **not** generate mesh and does **not** pretend to solve PLC issues.

Its job is narrower:

- consume existing `esp_rebuilt` normalized-geometry artifacts
- translate them into local topology strips that are easier to classify than raw surface IDs
- preserve section lineage, seam adjacency, closure adjacency, and reserved local descriptors
- provide a stable input contract for motif classification and pre-PLC audit work

## Current v1 Extraction Mode

`v1` is intentionally `artifact_inferred_section_strip_decomposition`.

That means:

- patches are inferred from adjacent rule-section intervals in `topology_lineage_report.json`
- curves / loops / corners are synthetic topology entities built from the same lineage data
- this is a classifier-facing local topology view, not a claim of exact native BREP edge ownership

## Required Top-Level Fields

- `contract`
- `component`
- `geometry_source`
- `geometry_provider`
- `normalized_geometry_path`
- `extraction_mode`
- `topology_counts`
- `topology_artifacts`
- `patches`
- `curves`
- `loops`
- `corners`
- `adjacency_graph`

## Local Entity Expectations

Each `patch` should carry at least:

- `patch_id`
- `patch_kind`
- `source_patch_family`
- `curve_ids`
- `loop_ids`
- `corner_ids`
- `section_lineage`
- `seam_adjacency`
- `closure_adjacency`
- `local_descriptors`

`local_descriptors` intentionally reserves fields for:

- `collapse_indicators`
- `local_clearance_m`
- `dihedral_consistency`
- `orientation_consistency`
- `extrusion_compatibility`

## Important Limitation

`topology_ir.v1` is a compiler input layer for family-level reasoning.

It is not:

- a mesh contract
- a solver-entry contract
- proof that the topology family is already repairable
