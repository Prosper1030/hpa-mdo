# Fine TE-Fixed Solver Report (Phase 4)

Verdict: `Fine solver attempted after TE checkMesh blocker was removed, but no stable Fine solution exists`

The Fine solver was run only after the regenerated mesh reported:

- open cells: `0`
- negative-volume cells: `0`
- wrong-oriented face pyramids: `0`
- `checkMesh -meshQuality` return code: `0`

The remaining mesh warning is the inherited low-determinant / face-twist
`meshQualityFaces` warning, not the lower-TE body/wake blocker.

## Solver Setup

No physics or force-definition changes were made:

| item | value |
|---|---|
| solver | `simpleFoam` |
| turbulence model | `SpalartAllmaras` |
| rho | `1.225 kg/m^3` |
| velocity | `6.5 m/s` |
| AoA | `0.18 deg` |
| Sref | `33.420059598 m^2` |
| Cref | `1.003721543 m` |
| primary force group | `airfoil_upper + airfoil_lower` |
| total physical group | `primary + te_wall` |
| artificial tip treatment | `physical_tip_left/right` excluded from physical drag; symmetry-plane policy |

## Cold Fine Run

Artifact:
`fine_te_radial_chord_shift_run/openfoam_cases/fine/fullwing_artificial_tip_symmetry/log.simpleFoam_200`

The run tripped the existing runaway guard immediately:

```text
RUNAWAY_GUARD triggered at pseudo-time 1;
terminating simpleFoam because |CD|>1 or |CL|>3 on the primary force group.
```

Last available row:

| group | time | CD | CL | CmPitch | status |
|---|---:|---:|---:|---:|---|
| primary | `1` | `3.950888` | `7.796553` | `-2.030124` | invalid, runaway guard |
| total_physical | `1` | `3.954488` | `7.796247` | `-2.025690` | invalid, runaway guard |

Pressure / viscous split for that invalid first row:

| group | CD pressure | CD viscous | CD pressure + viscous |
|---|---:|---:|---:|
| primary | `3.744546687` | `0.206340614` | `3.950887301` |
| total_physical | `3.748120882` | `0.206366685` | `3.954487567` |

Residuals were only available for the first pseudo-time step and are not a
converged trend:

```text
Ux last initial/final: 0.128736 / 0.00626831
p  last initial/final: 0.0354502 / 0.00330563
```

## Warm-Start Status

A Medium/reference warm-start was attempted with `mapFields` in the local
workspace during debugging. It did not produce a stable Fine run before this
artifact package was finalized, and no warm-start force window is accepted here.
The committed evidence therefore keeps the cold bounded run as the formal Fine
solver artifact.

## Engineering Read

The Fine mesh now reaches the solver gate, but the aerodynamic result is not
physically usable. A first-row `CD~3.95` and `CL~7.80` at `AoA=0.18 deg` is an
order-of-magnitude failure relative to the accepted route-smoke
(`CD_primary=0.03276165`, `CL_primary=1.133291`). This is a solver/setup/field
robustness blocker after the mesh topology blocker, not grid convergence.
