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
- `boundary_recovery_error_2_risk`
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
- observed topology failures and BL compatibility failures are tracked separately in the summary
- `extrusion_self_contact_risk` is treated as the BL-thickness / local-clearance compatibility line, not as proof of topology repair success
- `boundary_recovery_error_2_risk` is reserved for the downstream post-band transition family after the segment-facet string has already been displaced

## BL Clearance Compatibility Gate

`pre_plc_audit.v1` now carries a dedicated BL compatibility summary with:

- `total_bl_thickness_m`
- `min_local_clearance_m`
- `clearance_to_thickness_ratio`
- `verdict`

This gate is intentionally separate from observed topology failures such as:

- `segment_facet_intersection_risk`
- `facet_facet_overlap_risk`
- `boundary_recovery_error_2_risk`

## Planning Policy Promotion

When the BL clearance verdict is already `insufficient_clearance`, the artifact should also promote that into
a separate planning-policy block instead of leaving it as a late report-only observation.

The dedicated planning-policy fields are:

- `planning_policy`
- `planning_policy_fail_kinds`

Current v1 meaning:

- `blocking_topology_check_kinds` tells you which topology-side families are still blocking
- `blocking_bl_compatibility_check_kinds` tells you the BL compatibility checks that failed
- `planning_policy_fail_kinds` tells you that the route should already be read as a BL-policy block, not as a topology-operator miss

The first explicit planning-policy fail kind is:

- `bl_clearance_incompatibility`

## Important Limitation

`pre_plc_audit.v1` is not a full PLC solver or reproducer.

It is an honest front-loaded audit artifact so later work can target the right family with better evidence.
