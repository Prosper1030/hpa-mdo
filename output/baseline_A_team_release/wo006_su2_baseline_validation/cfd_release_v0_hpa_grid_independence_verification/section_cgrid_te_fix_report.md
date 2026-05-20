# Section-CGrid TE Fix Report (Phase 2)

Verdict: `generator-level lower-TE face-pyramid blocker fixed; CFD still not qualified`

The lower-TE blocker is fixed in the generator, not by editing `constant/polyMesh`.
The changed code is in:

- `scripts/cfd_rescue/section_cgrid.py`
- `scripts/cfd_rescue/swept_cgrid.py`
- `tests/test_wo006_lower_te_sliver_regression.py`

## Chosen Fix

The accepted fix is a local radial wall-layer rebalance at the lower TE:

```text
lower_te_radial_chord_shift_factor = 0.4
lower_te_radial_chord_shift_layers = 4
lower_te_radial_chord_shift_plateau_layers = 2
```

At the lower-TE path end (`perim_idx == n_path - 1`), the first few radial nodes
are shifted upstream by an amount proportional to the base first-layer height:

| radial layer | shift |
|---:|---:|
| `1` | `0.4 * 5e-5 = 2.0e-5 m` |
| `2` | `2.0e-5 m` |
| `3` | `1.0e-5 m` |
| `4` | `5.0e-6 m` |

The wall point itself (`i_radial=0`) is unchanged, so the airfoil geometry,
AoA, reference area, turbulence model, force groups, and closure/tip policy are
not altered. This is strategy 3 from the prompt: radial wall-layer rebalance near
TE. The earlier TE-corner first-layer widening remains in the generator as a
documented local smoothing/margin mechanism:

```text
te_corner_first_layer_growth = 2.0
te_corner_radial_blend_layers = 6
te_corner_perim_blend_cells = 3
```

The downstream wake-sleeve hook in `swept_cgrid._wake_interior_point` remains
wired but disabled by default (`te_sleeve_downstream_factor = 0.0`) because the
experimental downstream-push route introduced new quality problems faster than
it removed the TE blocker.

## Why This Fix Works

The failed face was shared between:

- airfoil-perim owner cell at `(i_chord = 239, i_radial = 0)`
- wake-extension neighbour cell at `(i_wake = 3, i_radial = 0)`

Both cells were slivers in the same geometric direction. The small upstream
chord shift on the lower-TE radial column moves the airfoil owner centroid back
to the opposite side of the shared face plane. Extending the same shift through
the first few radial layers prevents the bug from simply moving outward to
`i_radial=1`.

## Verification

Python regression contract:

```text
PYTHONPATH=scripts:hpa_meshing_package/src .venv/bin/python -m pytest \
  tests/test_wo006_lower_te_sliver_regression.py -v

4 passed in 411.49s
```

OpenFOAM full-wing Fine check:

```text
checkMesh -meshQuality

Face pyramids OK.
faces with face pyramid volume < 1e-18: 0
open cells: 0
negative volume cells: 0
maxNonOrtho: 87.516
maxSkew: 3.46221
Failed 1 mesh checks.
```

The remaining `Failed 1 mesh checks` is the inherited low-determinant / face
twist `meshQualityFaces` warning already present in this structured BL family,
not the lower-TE wrong-oriented face-pyramid blocker.

## Engineering Boundary

This phase fixes the generator-level TE topology symptom that prevented the Fine
mesh from reaching solver-smoke. It does not make the Fine solver stable. The
subsequent Fine run still tripped the force-runaway guard at pseudo-time 1, so
Medium->Fine grid independence remains undemonstrated and design power must not
be updated.
