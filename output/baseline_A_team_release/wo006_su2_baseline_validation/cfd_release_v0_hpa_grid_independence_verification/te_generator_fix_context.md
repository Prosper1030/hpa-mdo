# TE Generator Fix Context (Phase 0)

This file is the Phase 0 handoff for the WO-006 generator-level TE fix.
It locks down what the previous pass proved and what the fix must
preserve, so the Phase 1 regression test, the Phase 2 generator change,
and the Phase 3+ verification all agree on the same target.

## Sources read

- `lower_te_interface_failure_localization.md`  (Phase 1 of previous pass)
- `lower_te_bad_faces.csv`                       (per-face decode)
- `finite_te_hblock_sleeve_fix_report.md`        (Phase 2 polyMesh-only investigation)
- `final_hpa_grid_independence_verdict.md`        (13-question status as restored by user)
- `scripts/cfd_rescue/section_cgrid.py`           (the 2D C-grid generator)
- `scripts/cfd_rescue/swept_cgrid.py`             (the 3D mesh assembler)
- `constant/polyMesh` of `fine_te_fix_blend1_wake4_smoke`  (the failing mesh)

## Why polyMesh surgery is forbidden

Two polyMesh-only fixes were attempted in the previous pass; both made the
mesh strictly worse:

| attempt | what it did | result |
|---|---|---|
| Vertex shift (`1 mm` amplification of the wake-side vertex offset) | rewrote `constant/polyMesh/points` to push the 101 wake-side vertices of the bad faces by `~1 mm` along their existing `5 × 10⁻⁵ m` offset direction | 168 negative-volume cells, 904 wrong-oriented face pyramids, `max non-ortho = 180°`, failed 6 checks (was 2) |
| `removeFaces -overwrite wrongOrientedFaces` | merged each owner / neighbour pair into a polyhedron, deleting the 100 bad faces | 226 NEW wrong-oriented face pyramids on the merged polyhedra, `max skew = 4.12` (was 3.46), failed 3 checks |

Why neither works: the bad face's owner (airfoil-perim cell at
`(i_chord=239, i_radial=0)`) and neighbour (wake-extension cell at
`(i_wake=3, i_radial=0)`) are BOTH slivers in the same geometric
direction. There is no local point shift that can untangle them without
inverting at least one cell, and there is no local face removal that
yields a non-sliver polyhedron because the merged volume is still
controlled by the sliver edges.

The defect has to be removed at the source — the half-wing-seed topology
emitted by `scripts/cfd_rescue/section_cgrid.py` and
`scripts/cfd_rescue/swept_cgrid.py`. That is what Phase 2 of this pass
will change.

## Why generator-level is the correct fix layer

Tracing the generator (`section_cgrid.build_section_cgrid` +
`swept_cgrid.build_swept_cgrid_mesh`):

- `section_cgrid` produces a 2-D open-path C-grid at one airfoil
  section. The path goes from upper-TE corner (`index=0`) over upper
  surface, around LE, along lower surface, to lower-TE corner
  (`index=n_path-1`). At the TE corners the wall normal is set to the
  RADIAL direction from wall point to the local C-grid outer corner
  at `(x_downstream, ±height)`. With `te_normal_blend_points=1` only
  the very last cell of the perimeter blends between tangent-normal
  and radial-normal.
- `swept_cgrid._wake_interior_point` closes the C-grid by linearly
  interpolating, at each radial layer, between the airfoil's
  upper-TE column (`grid.points[r][0]`) and lower-TE column
  (`grid.points[r][n_path-1]`) across `wake_cross_cells = 4` cells.
  At cross=0 and cross=wake_cross_cells the wake vertex IDs are
  REUSED from the airfoil path-endpoints (`wake_node(s, r, 0) =
  node(s, r, 0)`; `wake_node(s, r, wake_cross_cells) = node(s, r,
  n_path-1)`). No vertex ID duplication exists; the "duplicate"
  appearance in the prior pass was a misinterpretation.

The geometric defect:

- **Airfoil's last perim cell** at `(i_chord=239, i_radial=0)` is a
  sliver. Its chordwise step (perimeter step at the lower-TE corner)
  is small. Its radial step is exactly `first_layer_height_m = 5e-5 m`.
- **Wake's last cross cell** at `(i_wake=3, i_radial=0)` is also a
  sliver. Its cross step at the wall layer is the `1 / wake_cross_cells
  = 0.25` fraction of the TE-base length (≈ 0.25 × TE thickness).
  Its radial step is the same `5e-5 m`.
- **The shared face between them** sits at the airfoil's path-end
  column (`index = n_path-1`), in the (radial, section) plane. It is
  a `5e-5 m × 0.229 m` ribbon, with a `~1.3e-5 m` non-planar twist
  caused by the per-section variation of the 3-D `radial` vector
  under the wing's local taper / sweep / dihedral transform.
- OpenFOAM's `checkMesh` face-pyramid volume test then fails because
  the SIGNED pyramid volume of the face × owner / face × neighbour
  flips sign at the twist plane, so the magnitude falls below the
  `10⁻¹⁸` cutoff.

The defect is therefore (1) two cells that are slivers in the same
direction and (2) a non-planar face between them. Both originate in
the section / swept generator, not in any later post-processing step.

## Exact local cell signature to preserve as regression test

The Phase 1 regression test must trigger ONLY on this combination
(this is the contract):

```
owner cell:
  zone       == "airfoil_perim"
  i_chord    == n_perim - 1            # the LAST airfoil-perimeter cell at TE wrap end
  i_radial   == 0                       # the wall-adjacent radial layer
neighbour cell:
  zone       == "wake_extension"
  i_wake     == wake_cross_cells - 1   # the wake cell closest to the airfoil's path-end
  i_radial   == 0
spanwise scope:
  inboard, both hemispheres (in the full-wing mirror mesh).
face geometry:
  4 distinct vertices forming a "ribbon" quadrilateral
  shorter pair of edges has length ≈ first_layer_height_m
  longer pair of edges spans one spanwise cell width
  non-planar twist ≥ ~1.3e-5 m (the SIGNED twist that flips face
  pyramid sign on at least one of owner/neighbour)
checkMesh signature:
  -meshQuality reports `face pyramid volume < 1e-18` on this face
  and "Error in face pyramids: N faces are incorrectly oriented"
  for N ≥ 1
```

## What the fix must preserve

- Airfoil geometry (`station.airfoil_xz`) and all physics parameters
  (`rho=1.225`, `V=6.5`, `nu=1.4607e-5`, AoA `0.18°`, `Sref`, `Cref`,
  Spalart-Allmaras turbulence, no transition model).
- Force-group definition: primary = `airfoil_upper + airfoil_lower`;
  `total_physical` = primary + `te_wall` (+ `physical_tip_*` when
  `symmetryPlane`).
- Closure / tip-patch policy: the current codex-line family keeps
  `physical_tip_left/right` as `symmetryPlane`. Slip closures are
  policy on the old sliding-window family only; both lines stay
  as-is.
- All hex topology. No new patch types. Patch counts and roles must
  match between the pre-fix and post-fix mesh.
- The accepted half-wing-seed cell-count target stays the same
  (`1,854,400` half-wing → `3,708,800` mirror = `3.71 M` fine).
  We are NOT remeshing globally.

## What the fix is allowed to change

Within the user-allowed strategy set:

1. **TE normal-blend extension** (modify `_open_wall_normals` /
   `te_normal_blend_points`).
2. **Lower-TE perimeter-step widening** (regularize the chordwise
   spacing of the last 1–3 perimeter cells at upper-TE and lower-TE
   wrap ends).
3. **Wall-layer radial spacing rebalance near TE corners** (e.g.
   local first-layer-height bump at the last 1–3 perimeter cells of
   each TE wrap end).
4. **Finite-TE H-block / sleeve** (1–3 local transition cells if
   needed).
5. **Wake cross-cell widening at wall** (non-uniform `t` for the
   first few radial layers in `_wake_interior_point`).

The Phase 2 fix implemented in this pass is documented in
`section_cgrid_te_fix_report.md`. It uses strategy 3 (local radial
wall-layer rebalance near the lower TE) with an O(first-layer-height)
upstream chord shift on the first few lower-TE radial layers. The
existing TE-corner widening remains as a smoothing / margin mechanism.
This is a generator-level coordinate policy, not post-generated
polyMesh surgery.

## What the fix is NOT allowed to do

- No global remeshing.
- No change to the airfoil profile beyond the already-accepted TE
  regularization policy that produced the current `airfoil_xz`.
- No `transformPoints` / `removeFaces` / `mergePoints` post-processing
  to patch the polyMesh after generation.
- No looser solver tolerances or BC changes to hide a still-bad mesh.
- No change to the patch types or to the closure-slip / symmetryPlane
  policy.

## Phase / commit gating contract

1. Regression tests for the lower-TE sliver signature land first
   (Phase 1).
2. Generator fix lands second (Phase 2), and the regression tests
   must now pass.
3. Fine mesh regeneration + strict `checkMesh -meshQuality` evidence
   lands third (Phase 3). Mesh must have `0` wrong-oriented face
   pyramids.
4. Fine solver evidence (Phase 4) only after Phase 3 passes.
5. Final verdict (Phase 5) compares Medium → Fine.
6. Commit lands only if Phases 1–3 are real (artifacts on disk,
   tests green) AND either Phase 4 is real or there is an explicit
   generator-level blocker recorded.
