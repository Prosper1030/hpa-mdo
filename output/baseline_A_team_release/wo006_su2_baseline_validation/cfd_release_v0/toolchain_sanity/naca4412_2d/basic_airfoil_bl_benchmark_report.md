# WO-006R8 Basic Airfoil BL Benchmark

This is a diagnostic simple case, not Baseline A completion evidence.

## Case

- airfoil: `NACA4412`
- chord: `1.130190 m`
- velocity: `6.500 m/s`
- alpha: `4.000 deg`
- Reynolds number: `5.029e+05`
- expected CL sanity estimate: `0.658`
- expected CD scale: `0.006` to `0.080`

## Mesh

- nodes: `15645`
- cells: `25686`
- cell type counts: `{'2': 20475, '3': 5211}`
- BL quad count: `5211`
- markers: `['airfoil', 'farfield']`

## SU2

- run status: `completed`
- final CL: `0.9012756302`
- final CD: `0.02075585229`
- final CMy/CMz: `0.1035276432`
- coefficient gate: `pass`

## Assessment

- status: `basic_sanity_case_available`
- blockers: `[]`
- CFD_STATUS: `mesh_ladder_incomplete`
- GOAL_STATUS: `INCOMPLETE`
