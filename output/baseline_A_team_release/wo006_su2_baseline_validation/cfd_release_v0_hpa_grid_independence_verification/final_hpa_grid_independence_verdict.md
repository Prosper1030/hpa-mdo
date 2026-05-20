# Final HPA Grid-Independence Verdict

Verdict: `lower_te_generator_blocker_fixed_but_grid_independence_not_demonstrated`

The lower-TE sliver was fixed at the generator level well enough to remove the
Fine mesh's wrong-oriented face-pyramid blocker. The Fine solver still did not
complete a stable force window, so CD is not grid-independent and design power
must not be updated.

## Required Answers

1. Was the lower-TE sliver fixed at generator level?

   Yes for the localized wrong-oriented face-pyramid blocker. The fix lives in
   `section_cgrid.py` / `swept_cgrid.py`; no polyMesh surgery was used.
   Regression evidence: `4 passed in 411.49s` for
   `tests/test_wo006_lower_te_sliver_regression.py`.

2. Did Fine strict checkMesh pass?

   The hard lower-TE blockers passed: open cells `0`, negative volumes `0`,
   wrong-oriented face pyramids `0`, and OpenFOAM reported `Face pyramids OK`.
   `checkMesh -meshQuality` returned `0`, but still wrote `Failed 1 mesh checks`
   for inherited determinant/twist `meshQualityFaces` (`10` twist faces,
   `2,266,249` low-determinant faces). Treat this as solver-smoke acceptable,
   not a clean final validation mesh.

3. Did Fine solver run?

   It was attempted after the checkMesh gate, but it did not complete. The cold
   `simpleFoam` run tripped the existing force-runaway guard at pseudo-time `1`.

4. What are Medium and Fine CD/CL?

   Medium/reference route-smoke: `CD_primary=0.03276165`,
   `CL_primary=1.133291`, `CD_total=0.05708291`.

   Fine has no qualified stable CD/CL. Its invalid first row was
   `CD_primary=3.950888`, `CL_primary=7.796553`,
   `CD_total_physical=3.954488`, `CL_total_physical=7.796247`.

5. Is CD grid-independent?

   No. Medium->Fine convergence cannot be evaluated because the Fine solver did
   not produce a stable force window.

6. Can `CD~0.0315` be trusted?

   No, not as design-power truth. It remains route-smoke-scale evidence only
   until a same-family solver-complete Coarse/Medium/Fine ladder meets the CD,
   CL, y+, Cp/Cf, wake, and tip-vortex checks.

7. Can design power be updated, or is CFD still not qualified?

   Do not update design power. CFD is still not qualified.

## Current Blocker

The active blocker has moved:

```text
old blocker: Fine lower-TE body/wake wrong-oriented face pyramids
new blocker: Fine solver stability / initialization / numerical robustness after TE-fixed mesh generation
```

The engineering interpretation is important: passing the TE face-pyramid gate
only proves the generator no longer emits that localized invalid interface. It
does not prove aerodynamic convergence, physical pressure recovery, or
manufacturing/design readiness.
