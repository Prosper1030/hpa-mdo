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
- `POST_BAND_TRANSITION_BOUNDARY_RECOVERY` means a deterministic guard split has localized the downstream `error 2` family to the guard-to-tip boundary-recovery interval and can dispatch one bounded regularization operator inside that interval
- `VOLUME_ENTRY_PLC_RISK` means `pre_plc_audit.v1` already sees a blocking or warning-level risk family before 3D generation

## Important Limitation

`motif_registry.v1` is only classification and dispatch metadata.

It does not mean the listed operator is implemented or safe to auto-apply.
