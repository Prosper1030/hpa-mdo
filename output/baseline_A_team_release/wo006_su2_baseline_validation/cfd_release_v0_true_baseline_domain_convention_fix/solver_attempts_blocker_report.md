# Solver Attempts Blocker Report

All attempts used the same accepted true Baseline swept C-grid mesh, corrected
half-wing patch roles, `root_symmetry` on the original `tip_left` y=0 plane,
Spalart-Allmaras, `V=6.5 m/s`, and `AoA=0.18 deg`. No mesh topology, geometry,
airfoil, span, station count, or TE gap was changed.

| attempt | solver setup | stop point | result |
|---:|---|---|---|
| 1 | previous route relaxation / linearUpwind | stopped after iteration 88 | numerical force runaway; `Cd_primary` reached `31.7614` at iteration 86 and remained wildly oscillatory |
| 2 | conservative relaxation, same schemes | stopped after iteration 54 | numerical force runaway; `Cd_primary` reached `18.0282` at iteration 50 and `12.0529` at iteration 52 |
| 3 | bounded upwind + conservative relaxation | stopped at iteration 37 | still unstable; final parsed primary window spans `Cd=-4.867..7.608`, `Cl=-12.812..19.856`, route-smoke stability fail |

The failure is not a missing BC entry or a root-symmetry patch-type error:
`checkMesh -meshQuality` returned `0`, `simpleFoam -dry-run` returned `0`, and
all fields contain `root_symmetry` `symmetryPlane` entries. The blocker is the
corrected half-wing symmetry convention making this high-nonorthogonal
structured mesh numerically unstable before a valid 500-iteration route-smoke.
