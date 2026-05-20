# TE Sliver Regression Test Report (Phase 1)

Verdict: `regression contract green after generator-level lower-TE rebalance`

Phase 1 added `tests/test_wo006_lower_te_sliver_regression.py`, a pure-Python
regression contract for the lower-TE body/wake interface blocker. The test
reproduces the production Fine C-grid family (`scale=1.25`, `n_perim=240`,
`n_radial=80`, `span_cells=95`, `wake_cross_cells=4`,
`first_layer_height_m=5e-5`) and inspects the exact shared face localized in
`lower_te_interface_failure_localization.md`.

## Pinned Failure Signature

The contract preserves this local decode:

| item | value |
|---|---|
| owner | airfoil-perimeter cell |
| owner indices | `i_chord = n_perim - 1`, `i_radial = 0` |
| neighbour | wake-extension cell |
| neighbour indices | `i_wake = wake_cross_cells - 1`, `i_radial = 0` |
| full-wing prior count | `100` wrong-oriented face pyramids |
| half-wing prior count | `50 / 95` spanwise lower-TE body/wake faces |

The original face is a 4-vertex ribbon at the lower-TE path end. OpenFOAM flags
it because the owner and neighbour centroids land on the same side of the
shared face plane, producing same-sign signed face-pyramid volumes.

## Tests

| test | purpose |
|---|---|
| `test_lower_te_face_orientation_at_production_fine_settings` | Production Fine lower-TE body/wake faces must have owner and neighbour on opposite sides of the face plane. |
| `test_lower_te_face_orientation_stays_clean_through_radial_rebalance_layers` | The fix must not merely move the bad orientation from `i_radial=0` to radial layers `1..3`. |
| `test_lower_te_face_is_already_acceptable_at_coarse_settings` | Coarse rung behaviour must not regress. |
| `test_lower_te_signature_owner_neighbour_indices_are_stable` | The localized owner/neighbour indexing contract must remain stable. |

## Red-Green Evidence

Before the final generator rebalance, the production Fine test was verified red:

```text
PYTHONPATH=scripts:hpa_meshing_package/src .venv/bin/python -m pytest \
  tests/test_wo006_lower_te_sliver_regression.py::test_lower_te_face_orientation_at_production_fine_settings \
  -v --runxfail

FAILED: 49/95 lower-TE body/wake faces are incorrectly oriented
```

After the generator-level lower-TE radial chord rebalance and the radial-layer
guard were added:

```text
PYTHONPATH=scripts:hpa_meshing_package/src .venv/bin/python -m pytest \
  tests/test_wo006_lower_te_sliver_regression.py -v

4 passed in 411.49s
```

This test suite is intentionally expensive because it builds the Fine-scale
half-wing seed. It is still cheaper and more portable than requiring OpenFOAM in
unit-test environments, while preserving the same signed face-pyramid
orientation condition that `checkMesh -meshQuality` reports.

## Engineering Read

The regression tests prove the lower-TE body/wake interface orientation bug no
longer exists in the generator at the pinned Fine scale. They do not prove
solver convergence, grid independence, y+ acceptability, wake/tip-vortex
stability, or design-power validity.
