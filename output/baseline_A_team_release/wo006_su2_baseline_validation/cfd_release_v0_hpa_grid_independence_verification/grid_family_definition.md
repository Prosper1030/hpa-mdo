# HPA Grid Family Definition

Verdict: `candidate_family_defined_but_not_released`

This is the current same-family swept C-grid candidate for the WO-006 true
Baseline A OpenFOAM grid-independence workflow. It is not a passed grid family.

## Same-Family Contract

- geometry: true Baseline A authority geometry
- AoA: `0.18 deg`
- rho / V / nu: `1.225 kg/m^3` / `6.5 m/s` / `1.4607e-5 m^2/s`
- turbulence model: Spalart-Allmaras, no transition model
- reference area / length: `Sref=33.420059598 m^2`, `Cref=1.003721543 m`
- topology: swept wake C-grid with finite trailing-edge wall and full-wing mirror
- first layer height: `5e-5 m`
- wall-normal growth: `1.12`
- farfield: `10 chords`
- wake length: `8 chords`
- force definition: `total_physical = primary + te_wall`; artificial mirror tip closures excluded

## Current Ladder

| rung | scale | n_perim | n_radial | half-span cells | wake_cross_cells | TE normal blend |
|---|---:|---:|---:|---:|---:|---:|
| coarse | 0.75 | 144 | 48 | 61 | 4 | 1 |
| medium | 1.00 | 192 | 64 | 78 | 4 | 1 |
| fine | 1.25 | 240 | 80 | 95 | 4 | 1 |

## Current Fine Smoke

The repaired Fine smoke at `fine_te_fix_blend1_wake4_smoke` generated a
`3,708,800` cell full-wing mesh. It fixed the previous open-cell blocker:

- max cell openness: `4.98214e-14`
- open cells: `0`
- negative volumes: `0`
- max non-orthogonality: `88.4382 deg`
- max skew: `3.46221`

It still fails strict checkMesh:

- wrong-oriented face pyramids: `100`
- failed meshQuality checks: `2`
- exact localization: lower TE body/wake interface at radial layer 0

Hard stop: do not run the final C/M/F solver family until this lower-TE
finite-gap interface is repaired with a proper H-block/sleeve topology.
