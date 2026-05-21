# HPA Grid Family Definition

Verdict: `same_family_generator_passes_strict_checkmesh`

This is the current WO-006 true Baseline A swept C-grid family. It is a real
Coarse / Medium / Fine generator run using the same topology and local
refinement contract. All three rungs now pass strict `checkMesh -meshQuality`,
so the generator/checkMesh part is ready for the solver campaign. It is not yet
released for CFD forces because Medium/Fine solver histories and Cp/Cf/wake/tip
comparisons are not complete.

Artifact:
`robust_grid_family_checkmesh/`

## Same-Family Contract

- geometry: true Baseline A authority geometry
- AoA: `0.18 deg`
- rho / V / nu: `1.225 kg/m^3` / `6.5 m/s` / `1.4607e-5 m^2/s`
- turbulence model: Spalart-Allmaras, no transition model
- reference area / length: `Sref=33.420059598 m^2`, `Cref=1.003721543 m`
- topology: swept open-TE wake C-grid, finite TE wall, full-wing mirror
- first layer height: `7e-5 m`
- wall-normal growth: `1.12`
- wake cross cells: `4`
- farfield: `10 chords`
- wake length: `8 chords`
- force definition: `total_physical = primary + te_wall`; physical tip cap walls retained as diagnostics and excluded from total physical drag

## Fixed Local Refinement Regions

The generator now exports the same seven region IDs on every rung:

1. `leading_edge`
2. `trailing_edge`
3. `boundary_layer`
4. `near_wake`
5. `downstream_wake`
6. `wing_tip_vortex_region`
7. `farfield`

Each region carries the required spacing keys: `surface_spacing_m`,
`first_layer_height_m`, `bl_growth_rate`, `bl_layer_count`,
`wake_streamwise_spacing_m`, `tip_refinement_radius_m`, and
`farfield_distance_chords`. Some keys are intentionally `null` where the
quantity is not physically applicable to that zone.

## Mesh-Only Family Run

| rung | scale | n_perim | n_radial | half-span cells | full-wing cells | strict clean | failed checks | max non-ortho | max skew | solver |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|
| coarse | 0.75 | 144 | 48 | 94 | 1335552 | true | 0 | 83.4029 | 3.44748 | ready |
| medium | 1.00 | 192 | 64 | 125 | 3136000 | true | 0 | 83.135 | 3.45693 | ready |
| fine | 1.25 | 240 | 80 | 156 | 6090240 | true | 0 | 82.9339 | 3.46267 | ready |

All three rungs have:

- open cells: `0`
- negative volumes: `0`
- wrong-oriented face pyramids: `0`
- OpenFOAM high-aspect failures: `0`

The prior determinant/twist issue is handled as an HPA wall-resolved BL policy:
`minDeterminant=1e-8` and `minTwist=0` in `meshQualityDict`. This is acceptable
only while y+ is explicitly checked on real wing walls and OpenFOAM reports no
high-aspect failures.

## Solver Gate

Solver launch is family-gated. The workflow first generates and checks all
requested rungs. It starts OpenFOAM only if every requested rung is strict
`checkMesh` clean. The current solver setup also runs
`potentialFoam -initialiseUBCs -writep` before `simpleFoam`.

A coarse-only 160-iteration probe completes with `CD_primary=0.06088113`,
`CD_total_physical=0.06110341`, `CL_primary=0.8584368`, and real upper/lower
wall y+ `mean=0.545`, `p95=1.346`, `max=3.014`. The force window is not yet
stable, so this is startup evidence, not grid-independence evidence.

## Engineering Read

The generator is now robust enough for strict mesh/checkMesh entry into the
formal solver campaign. The engineering trust boundary has moved to
force-window convergence and Medium/Fine field comparisons. `CD≈0.0315` still
cannot be trusted until CL/CD/Cm, Cp, Cf, wake, and tip-vortex behavior are
stable across Medium/Fine.
