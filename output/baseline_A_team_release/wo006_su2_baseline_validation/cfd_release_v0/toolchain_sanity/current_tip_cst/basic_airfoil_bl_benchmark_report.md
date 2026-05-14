# WO-006R8 Basic Airfoil BL Benchmark

This is a diagnostic simple case, not Baseline A completion evidence.

## Case

- airfoil: `cst_tip_nsga2_g05_child_0032_70ef8136`
- chord: `0.645004 m`
- velocity: `6.500 m/s`
- alpha: `4.000 deg`
- Reynolds number: `2.870e+05`
- expected CL sanity estimate: `0.658`
- expected CD scale: `0.007` to `0.080`

## Mesh

- nodes: `13680`
- cells: `22491`
- cell type counts: `{'2': 17983, '3': 4508}`
- BL quad count: `4508`
- markers: `['airfoil', 'farfield']`

## SU2

- run status: `completed`
- final CL: `0.6316180442`
- final CD: `0.02047500345`
- final CMy/CMz: `0.01129809188`
- coefficient gate: `pass`

## Assessment

- status: `basic_sanity_case_available`
- blockers: `[]`
- CFD_STATUS: `mesh_ladder_incomplete`
- GOAL_STATUS: `INCOMPLETE`
