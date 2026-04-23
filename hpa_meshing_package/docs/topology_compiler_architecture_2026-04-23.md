# Topology Compiler v1 Architecture Note (2026-04-23)

## Why this round moves from single-case repair to topology compiler

The current blocker is no longer the older closure-ring / single-face patch problem by itself.

The real-wing BL line has already pushed the main uncertainty further downstream:

- 3D volume-side consistency
- solver-entry family behavior
- PLC / degenerated-prism style risk that is larger than one broken patch

At that point, continuing to hard-patch one case at a time becomes misleading.

What we need first is a family-level compiler skeleton:

- a topology-first IR
- a named motif registry
- an explicit operator library
- a pre-PLC audit artifact

That gives later work a clean place to land without pretending this round already repaired every real-wing prelaunch failure.

## Role split: shell_v3, shell_v4, esp_rebuilt, compiler layer

### `esp_rebuilt`

`esp_rebuilt` remains the normalized-geometry producer.

It already emits the artifacts this v1 compiler consumes:

- `topology.json`
- `topology_lineage_report.json`
- `topology_suppression_report.json`

The compiler layer sits **after** those artifacts, not inside the provider runtime.

### `shell_v3`

`shell_v3` stays frozen.

Its job is still:

- frozen geometry baseline
- coarse CFD baseline
- regression reference

It is explicitly **not** reopened as the BL mainline and this compiler layer does not give it permission to mutate that role.

### `shell_v4`

`shell_v4` remains the active BL / solver-validation branch.

Its job is:

- real-wing BL topology exploration
- solver-entry contract exploration
- future consumption of topology-family artifacts

It does **not** become the new geometry baseline just because it is the active validation branch.

### `topology compiler v1`

The new compiler layer is a separate planning/analysis stratum between provider artifacts and family-level operator work.

Its current outputs are:

- `topology_ir.v1`
- `motif_registry.v1`
- `operator_plan.v1`
- `pre_plc_audit.v1`
- `topology_compiler.v1`

This keeps the architecture honest:

- `esp_rebuilt` materializes geometry
- compiler classifies topology families
- `shell_v4` later consumes those families for BL / solver-entry work
- `shell_v3` remains the frozen regression truth

## What is complete in this round

- versioned compiler package under `src/hpa_meshing/compiler/`
- `topology_ir.v1` models plus builder from existing `esp_rebuilt` artifacts
- `motif_registry.v1` with the requested first-wave motif kinds
- `operator_library.v1` with explicit contracts and skeleton results
- `pre_plc_audit.v1` schema plus minimal implemented guards for loop consistency and local-clearance-vs-first-layer-height
- `topology_compiler.v1` artifact writer and shell-role policy split
- tests for schema, registry wiring, deterministic reject, and shell role separation

## What is intentionally still skeleton / TODO

- no operator except deterministic reject actually repairs geometry
- no native BREP-edge extraction yet; `topology_ir.v1` currently uses artifact-inferred section strips
- no PLC reproducer yet for segment-facet or facet-facet families
- no automatic integration into the live `shell_v4` runtime path yet

Those are intentional boundaries, not missing polish.

The point of v1 is to expose the landing zones before another round of family-level implementation.

## Recommended next step after this round

1. Add a reproducible PLC-family fixture set and promote the current placeholder checks into real geometric audits.
2. Connect one real `shell_v4` family path to `topology_compiler.v1` under a clear feature gate, still plan-only by default.
3. Implement the first non-reject operator on a bounded family, most likely the truncation connector band or closure-ring fill path with dedicated artifacts.
