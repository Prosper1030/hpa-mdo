# Decision Tree

## If Fourier And AVL Do Not Align

1. Check definitions:
   - `eta`,
   - `theta`,
   - `Lprime`,
   - `cl*c`,
   - circulation proxy,
   - normalized loading,
   - half-span/full-span convention.
2. Fit AVL actual loading into Fourier coefficients.
3. Compare commanded coefficients to realized coefficients.
4. If mismatch is mostly convention-based, fix the convention and rerun the
   bridge.
5. If mismatch is outer-underloading:
   - try geometry authority changes,
   - try smooth chord redistribution,
   - try twist/incidence changes,
   - test whether airfoil alpha_L0/camber could shift local loading,
   - test loaded-dihedral effects.
6. If AVL reference setup is suspect, audit `Sref`, `Bref`, `Cref`, trim CL, and
   section coordinates.
7. If no bounded change aligns the spanload, declare geometry authority blocker.

## If 6-7 Deg Is Too Heavy

1. Verify that `6-7 deg` refers to total cruise effective dihedral, not extra
   elastic deflection.
2. Audit aerodynamic surface z vs beam-line z.
3. Confirm mass basis.
4. Check whether clearance fails because of jig shape, root reference, or
   manufacturing assumption.
5. Search nearby loaded `z(y)` families:
   - smoother shape,
   - different root-to-tip distribution,
   - local control-station changes,
   - wire layout if available.
6. Test credible tube recipe variants in the `10.5-14 kg` range.
7. If `6-7 deg` still cannot pass, find the nearest practical compromise and
   quantify:
   - mass penalty,
   - clearance penalty,
   - induced drag penalty,
   - local Cl penalty,
   - manufacturing penalty.
8. If the nearest compromise exceeds `10 deg` total effective dihedral, require
   explicit aero/manufacturing justification before promoting it.

## If Airfoil Raw Best Has Query Warning

1. Identify the zone and airfoil causing the warning.
2. Determine warning cause:
   - record not mission-grade,
   - outside polar envelope,
   - insufficient stall margin,
   - roughness coverage gap,
   - source metadata issue.
3. If a query-pass alternative exists with small power penalty, select the
   conservative alternative.
4. If raw best can be repaired by using existing Tier2 data, repair and rerun.
5. If repair requires new polars but not broad NSGA, generate the narrow missing
   polar evidence.
6. If repair requires broad CST/NSGA, declare an airfoil database coverage
   blocker and ask for permission before running broad search.
7. Never promote warning-bearing raw best as production-facing.

## If Moment Closure Fails

1. Split the issue:
   - physical moment imbalance,
   - bookkeeping residual,
   - sign convention,
   - torque ownership,
   - half/full-span factor,
   - load application point,
   - wire/support reaction accounting.
2. Check whether force closure passes.
3. Check root torque and support reactions.
4. Compare direct `MY` torque ownership against available CalculiX/APDL evidence
   if a small comparable deck exists.
5. If physical balance fails, loop back to load mapping, torque ownership, or
   wire/support model.
6. If only bookkeeping is unresolved, label it
   `moment_bookkeeping_unresolved` and prevent final structural signoff while
   allowing screening comparison.
7. Do not use an unexplained moment closure flag as an automatic design-killer.

## If Closure Fails After Airfoil Selection

1. If raw/conservative query warning exists, return to airfoil selection.
2. If `e_CDi` changes by more than `5%`, return to Fourier-AVL / geometry
   authority.
3. If spanload changes by more than `8%`, return to Fourier-AVL / geometry
   authority.
4. If deflection changes by more than `10%`, return to structure-budgeted loaded
   shape.
5. If clearance goes negative, return to loaded-shape / jig basis.
6. If tube mass changes by more than `5%`, return to tube recipe / mass budget.
7. If wire tension changes by more than `10%`, return to wire layout /
   structural basis.
8. If power misses the preferred band but closure is stable, search bounded
   airfoil/spanload compromises before declaring mission-power blocker.

## If No Candidate Meets All Criteria

Declare blocker only after the relevant bounded loopbacks have been tried.

The blocker package must say:

- whether the blocker is physical or modeling;
- which workstreams were attempted;
- which thresholds failed;
- which candidate came closest;
- what design assumption must change next.
