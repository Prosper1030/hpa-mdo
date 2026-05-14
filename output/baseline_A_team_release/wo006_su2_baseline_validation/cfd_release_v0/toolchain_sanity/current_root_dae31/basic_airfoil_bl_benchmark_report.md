# WO-006R8 Basic Airfoil BL Benchmark

This is a diagnostic simple case, not Baseline A completion evidence.

## Case

- airfoil: `dae31`
- chord: `1.256773 m`
- velocity: `6.500 m/s`
- alpha: `4.000 deg`
- Reynolds number: `5.592e+05`
- expected CL sanity estimate: `0.658`
- expected CD scale: `0.006` to `0.080`

## Mesh

- nodes: `13008`
- cells: `21633`
- cell type counts: `{'2': 17595, '3': 4038}`
- BL quad count: `4038`
- markers: `['airfoil', 'farfield']`

## SU2

- run status: `completed`
- final CL: `1.150840666`
- final CD: `0.02117848483`
- final CMy/CMz: `0.1577954229`
- coefficient gate: `pass`

## Assessment

- status: `basic_sanity_case_available`
- blockers: `[]`
- CFD_STATUS: `mesh_ladder_incomplete`
- GOAL_STATUS: `INCOMPLETE`
