# HPA Grid Family Definition

Verdict: `same_family_generator_runs_but_strict_family_gate_blocks_solver`

This is the current WO-006 true Baseline A swept C-grid family. It is a real
Coarse / Medium / Fine generator run using the same topology and local
refinement contract, but it is not released for CFD forces because all three
rungs fail the strict `checkMesh -meshQuality` family gate.

Artifact:
`robust_grid_family_checkmesh/`

## Same-Family Contract

- geometry: true Baseline A authority geometry
- AoA: `0.18 deg`
- rho / V / nu: `1.225 kg/m^3` / `6.5 m/s` / `1.4607e-5 m^2/s`
- turbulence model: Spalart-Allmaras, no transition model
- reference area / length: `Sref=33.420059598 m^2`, `Cref=1.003721543 m`
- topology: swept open-TE wake C-grid, finite TE wall, full-wing mirror
- first layer height: `5e-5 m`
- wall-normal growth: `1.12`
- wake cross cells: `4`
- farfield: `10 chords`
- wake length: `8 chords`
- force definition if solver is later allowed: `total_physical = primary + te_wall`; artificial mirror tip closures excluded

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
| coarse | 0.75 | 144 | 48 | 61 | 866688 | false | 1 | 87.3826 | 3.44697 | blocked |
| medium | 1.00 | 192 | 64 | 78 | 1996800 | false | 2 | 89.193 | 3.45663 | blocked |
| fine | 1.25 | 240 | 80 | 95 | 3708800 | false | 1 | 87.516 | 3.46221 | blocked |

All three rungs have:

- open cells: `0`
- negative volumes: `0`
- wrong-oriented face pyramids: `0`
- faces with face pyramid volume `< 1e-18`: `0`

The remaining family blocker is the inherited structured-BL meshQuality set:

- coarse: `1,173,268` determinant `<0.001` faces
- medium: `1,861,547` determinant `<0.001` faces and `20` face-twist faces
- fine: `2,266,249` determinant `<0.001` faces and `10` face-twist faces

## Solver Gate

Solver launch is now family-gated. The workflow first generates and checks all
requested rungs. It starts OpenFOAM only if every requested rung is strict
`checkMesh` clean. In this run the gate blocked all solver phases, so no
`simpleFoam` or y+ post-processing was executed from the new C/M/F family.

## Engineering Read

The generator is better than the previous state because it no longer treats the
Fine lower-TE failure as a one-off repair. However, it is not yet robust enough
for aerodynamic grid independence. The next engineering blocker is reducing or
formally resolving the determinant/twist meshQuality failures without changing
geometry, BCs, force definitions, or the C/M/F topology contract.
