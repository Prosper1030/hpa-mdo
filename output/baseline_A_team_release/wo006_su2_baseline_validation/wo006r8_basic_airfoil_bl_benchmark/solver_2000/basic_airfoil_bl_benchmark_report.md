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

- nodes: `18281`
- cells: `31322`
- cell type counts: `{'2': 26489, '3': 4833}`
- BL quad count: `4833`
- markers: `['airfoil', 'farfield']`

## SU2

- run status: `completed`
- final CL: `0.8977773862`
- final CD: `0.02212081529`
- final CMy/CMz: `0.1029399452`
- coefficient gate: `pass`

## Assessment

- status: `basic_sanity_case_available`
- blockers: `[]`
- CFD_STATUS: `mesh_ladder_incomplete`
- GOAL_STATUS: `INCOMPLETE`
