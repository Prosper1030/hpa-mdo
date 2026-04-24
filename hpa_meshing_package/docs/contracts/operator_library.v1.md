# operator_library.v1

`operator_library.v1` is the explicit landing zone for topology-family repair operators.

## Purpose

This layer stops repair logic from staying hidden inside single-route patch code.

Instead, each operator exposes:

- which motif family it belongs to
- whether it is implemented or still skeleton-only
- which artifacts and report keys it must own

## Required v1 Operators

- `root_closure_from_bl_faces`
- `closure_ring_exact_wire_surface_fill`
- `extbl_termination_fallback_for_collapsed_endcap`
- `regularize_truncation_connector_band`
- `prototype_split_post_band_transition`
- `regularize_recoversegment_failed_steiner_post_band`
- `reject_unsupported_plc_risk_family`

## Expected Contract Shape

Each operator contract should expose at least:

- `operator_name`
- `implementation_status`
- `supported_motif_kinds`
- `expected_artifact_keys`
- `report_key`

`operator_plan.v1` is the machine-readable plan artifact produced from these contracts.

## Current v1 Behavior

- `regularize_truncation_connector_band` is the first implemented geometry-side operator
- it only regularizes the one-extra-pre-band-support family into a canonical 4-anchor connector-band topology
- `prototype_split_post_band_transition` is an honest executable prototype for the second observed family after connector-band canonicalization
- it inserts one deterministic synthetic section inside the post-band transition interval and uses changed downstream failure evidence as progress, not as a success claim
- `regularize_recoversegment_failed_steiner_post_band` is the third-family bounded operator after that split
- it creates a local guard / relief / terminal spacing plan for `boundary_recovery_error_2_recoversegment_failed_insert_steiner`
- it can recommend `local_transition_regularization`, `bl_stageback_required`, `tip_truncation_required`, `insufficient_clearance_budget`, or `unresolved_recovery_internal_bailout`
- it does not mutate the runtime BL specification; BL policy blocks remain separate through `topology_attempted_but_bl_policy_blocked`
- relief reruns that still hit `error 2` now carry `boundary_recovery_error_2_downstream_residual_classifier.v1`, including the failed-Steiner observed-candidate family when throw-site evidence exists, plus inferred/rejected fallback families such as `residual_contact_near_tip_terminal`, spacing insufficiency, angle jump, orientation conflict, and post-relief local-clearance evidence
- the other geometry operators remain **skeleton only**
- `reject_unsupported_plc_risk_family` is intentionally implemented as a deterministic reject, so unsupported PLC risk families are not silently ignored

## Important Limitation

`operator_library.v1` is not proof that topology repair already works.

The v1 goal is explicit contracts and honest status, not fake completeness.
