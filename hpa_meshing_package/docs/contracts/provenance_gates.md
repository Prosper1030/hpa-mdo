# Provenance Gates

The baseline SU2 line carries two formal provenance checks.

## 1. Reference Provenance Gate

This gate answers: where did `REF_AREA`, `REF_LENGTH`, and `REF_ORIGIN_MOMENT` come from?

Allowed source categories:

- `geometry_derived`
- `baseline_envelope_derived`
- `user_declared`

Current policy:

- prefer `geometry_derived` when OpenVSP reference data is available
- fall back to `baseline_envelope_derived` when geometry-derived reference quantities are unavailable
- allow `user_declared` override when the caller intentionally supplies reference quantities

## 2. Force-Surface Provenance Gate

This gate answers: what surface markers are actually being integrated for aerodynamic forces?

Current package-native baseline status:

- aircraft-assembly wall marker is expected to be `aircraft`
- aircraft-assembly scope is `whole_aircraft_wall`
- closed-solid fairing wall marker is expected to be `fairing_solid`
- closed-solid fairing scope is `component_subset`
- component labels may exist in geometry, but they are not yet mapped into per-component force integration

## Gate Status Semantics

- `pass`: the package can explain the provenance cleanly
- `warn`: the package can still run, but provenance is weaker or more approximate
- `fail`: the downstream CFD result should not be treated as a valid handoff

`overall_status` follows the usual precedence:

```text
fail > warn > pass
```

## Current Limitation

The presence of component labels in geometry does not yet imply component-level force mapping. Today that situation is reported explicitly as:

- `component_provenance=geometry_labels_present_but_not_mapped`

That is intentional, and it is one of the next roadmap items after convergence hardening.
