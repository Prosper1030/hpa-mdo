# Conservative Load Mapper Foundation

Date: 2026-05-09

## Scope

This report documents the first conservative aero-grid to structural-grid load
remap foundation for the current pathfinder line. It is infrastructure for the
next tail contract / full-aircraft trim audit and tail-aware bounded rib /
rear-spar stiffness sensitivity work. It is not aeroelastic sign-off, not a rib
FEM model, not a tail FEM model, not an ASWing-like runner, and not a final
aircraft load validation.

The implemented entry point is:

```python
from hpa_mdo.aero.load_mapper import ConservativeLoadMapper
```

The existing `LoadMapper` linear interpolation behavior remains unchanged.

## Method

`ConservativeLoadMapper` first calls the existing interpolation path to get
the target-grid load vector:

```text
x0 = interp(y_a, load_a, y_s)
```

It then applies a weighted constrained projection:

```text
x = x0 - W^-1 A^T (A W^-1 A^T)^+ (A x0 - b)
```

where `^+` is the pseudo-inverse. The first implementation uses structural
trapezoid integration weights with `W = diag(max(w_i, eps))`.

For `lift_per_span`, the conserved quantities are:

```text
total lift          = integral L(y) dy
root bending moment = integral y L(y) dy
```

For `torque_per_span`, the conserved quantity is:

```text
total pitching torque = integral T(y) dy
```

The mapper also conserves total drag by default as a scalar force integral, but
the current engineering gate is lift / root moment / torque.

## Diagnostics

Each conservative mapping output includes `conservation_diagnostics` with:

- source, before, after totals for lift, root bending moment, torque, and drag;
- before/after conservation errors;
- normalized correction L2 norm;
- max pointwise correction;
- sign reversal count;
- peak ratio;
- status: `conserved`, `conserved_with_large_correction`, or
  `conservation_projection_unphysical`;
- warning strings when the correction is large or nonphysical.

## Current Pathfinder Smoke

Smoke input:

- AVL load artifact:
  `output/phase10_2_canonical_inverse_design_check/smooth_tier2_candidate_avl_spanwise_loads.json`
- structural grid basis:
  `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary/smooth_tier2_canonical_config.yaml`
- aero stations: `34`
- structural stations: `60`
- half-span: `0.0 m` to `17.166143 m`

Observed diagnostics:

| quantity | source | interpolation before | projected after | before error | after error |
|---|---:|---:|---:|---:|---:|
| total lift [N] | 501.633440 | 501.283970 | 501.633440 | -0.349470 | 5.68e-14 |
| root bending moment [N m] | 3544.979541 | 3540.871197 | 3544.979541 | -4.108344 | 4.55e-13 |
| total torque [N m] | -65.006297 | -64.954207 | -65.006297 | 0.052090 | 0.0 |

Correction diagnostics:

| metric | value |
|---|---:|
| status | conserved |
| correction_l2_norm | 0.004477 |
| max_pointwise_correction | 0.003085 |
| sign_reversal_count | 0 |
| peak_ratio | 1.003085 |

Engineering read: on this current pathfinder artifact, the correction is small
and does not introduce load sign reversals or a visible peak. That makes the
existing interpolation error a small but real conservation defect, not a reason
by itself to reject the pathfinder load state.

## Engineering Boundary

This remap only enforces integrated load consistency between grids. It does
not prove:

- aeroelastic twist closure;
- rib load-transfer stiffness;
- rear spar stiffness realism;
- root fitting, wire attach, termination, or hardware detail;
- full-wing FEM / APDL sign-off;
- final aircraft certification-level loads.

If a future rib / rear-spar sensitivity run reports
`conserved_with_large_correction` or `conservation_projection_unphysical`, the
right engineering interpretation is not "the conservative mapper fixed it."
It means the original pathfinder structural loading confidence must be
downgraded. In that case, do not proceed directly to rib sensitivity as if the
load basis were clean; first inspect units, grid coverage, span station
alignment, sign conventions, torque convention, and whether the aero artifact
is the correct owner for the selected structure state.

The same rule applies when the mapper is extended to tail load packages. H-tail
lift / pitching moment, V-tail sideforce / yawing moment, and all-moving pivot
moments are aircraft load-ownership quantities. If the projection needs a large
or nonphysical correction, the pathfinder should be downgraded before using the
tail loads for trim, tailboom, pivot, or hardware conclusions.

## Tests

Focused tests are in `tests/test_load_mapper.py` and cover:

- nonuniform aero grid to uniform structural grid total lift conservation;
- root bending moment conservation;
- total torque conservation;
- interpolation not conserving before projection, then conserving after
  projection;
- too-few / degenerate station handling;
- NaN validation;
- unchanged legacy `LoadMapper` linear interpolation behavior.
