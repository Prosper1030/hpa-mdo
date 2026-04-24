# motif_registry.v1

`motif_registry.v1` promotes the current shell-family observations from ad hoc patch logic into named topology families.

## Purpose

The registry exists so downstream work can ask:

- which topology family is this local region in?
- which operators are admissible for that family?
- which conditions are explicit reject / unsupported states?
- which artifacts should exist if we later implement the operator?

This replaces the older habit of reasoning directly from unstable surface IDs.

## Required v1 Motif Kinds

- `ROOT_CLOSURE`
- `TRUNCATION_SEAM_REQUIRED_RING`
- `TRIANGULAR_ENDCAP_COLLAPSED_3PATCH`
- `TRUNCATION_CONNECTOR_BAND`
- `CANONICAL_CONNECTOR_BAND_POST_TRANSITION`
- `POST_BAND_TRANSITION_BOUNDARY_RECOVERY`
- `VOLUME_ENTRY_PLC_RISK`

## Each Match Carries

- `motif_id`
- `kind`
- `entity_ids`
- `summary`
- `predicate_evidence`
- `admissible_operators`
- `reject_conditions`
- `unsupported_conditions`
- `expected_artifact_keys`

## Current Minimal v1 Interpretation

- `ROOT_CLOSURE` means the local topology is adjacent to a symmetry/root closure family
- `TRUNCATION_SEAM_REQUIRED_RING` means tip-adjacent seam strips require a closure-ring style treatment family
- `TRIANGULAR_ENDCAP_COLLAPSED_3PATCH` means exactly three collapsed local endcap strips define the family
- `TRUNCATION_CONNECTOR_BAND` means the compiler has explicit connector-band descriptors and can dispatch the local regularization operator without surface-id patching
- `CANONICAL_CONNECTOR_BAND_POST_TRANSITION` means the overlap family is already gone and the remaining blocker still sits in the unsplit post-band transition strip
- `POST_BAND_TRANSITION_BOUNDARY_RECOVERY` means a deterministic guard split has localized the downstream `error 2` family to the guard-to-tip boundary-recovery interval and can dispatch the bounded `regularize_recoversegment_failed_steiner_post_band` operator inside that interval
- `VOLUME_ENTRY_PLC_RISK` means `pre_plc_audit.v1` already sees a blocking or warning-level risk family before 3D generation

For failed-Steiner evidence, `predicate_evidence` may also carry `residual_family`,
`evidence_level`, `throw_site_label`, `throw_site_file`, `throw_site_line`,
`local_surface_tags`, `local_y_band`, `suspicious_window`, `sevent_e_type`, and
`degenerated_prism_seen`. The motif rejects cases where the overlap family is still a blocker,
because this operator is bounded to the post-band recoversegment path and is not a generic
whole-wing or root-closure rewrite.

## Important Limitation

`motif_registry.v1` is only classification and dispatch metadata.

It does not mean the listed operator is implemented or safe to auto-apply.
