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
- `prototype_localize_post_transition_boundary_recovery`
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
- `prototype_localize_post_transition_boundary_recovery` is the third-family executable probe after that split
- it does not mutate geometry again; it localizes the `error 2` family to the guard-to-tip boundary-recovery locus and owns explicit artifacts/reject semantics
- the other geometry operators remain **skeleton only**
- `reject_unsupported_plc_risk_family` is intentionally implemented as a deterministic reject, so unsupported PLC risk families are not silently ignored

## Important Limitation

`operator_library.v1` is not proof that topology repair already works.

The v1 goal is explicit contracts and honest status, not fake completeness.
