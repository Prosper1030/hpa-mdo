# pre_plc_audit.v1

`pre_plc_audit.v1` moves 3D volume-entry risk discussion earlier in the pipeline.

## Purpose

Before `generate(3)` or later solver-entry claims, this audit should tell us:

- which risk families are already visible from topology-first descriptors
- which checks are implemented versus only reserved
- which artifact should be inspected before trying another single-case repair

## Required Checks

- `segment_facet_intersection_risk`
- `facet_facet_overlap_risk`
- `extrusion_self_contact_risk`
- `degenerated_prism_risk`
- `local_clearance_vs_first_layer_height`
- `manifold_loop_consistency`

## Each Check Carries

- `kind`
- `status`
- `implemented`
- `summary`
- `entity_ids`
- `metrics`
- `notes`

## Current Minimal v1 Interpretation

- `local_clearance_vs_first_layer_height` is a real guard when both inputs exist
- `manifold_loop_consistency` is a real consistency check on the inferred IR loops
- the other risk families remain placeholder-ready checks unless explicit flags are already present in the descriptors

## Important Limitation

`pre_plc_audit.v1` is not a full PLC solver or reproducer.

It is an honest front-loaded audit artifact so later work can target the right family with better evidence.
