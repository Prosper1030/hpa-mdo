# Corrected Boundary-Condition Policy

- mesh convention: `half-wing`
- `root_symmetry` uses OpenFOAM `symmetryPlane` patch and field BCs.
- `root_symmetry` is excluded from all `forceCoeffs` and `forces` functionObjects.
- main upper/lower walls, physical tip, and trailing edge use noSlip wall BCs.
- farfield/outlet keep the previous successful freestream/open convention.

| role | patches | U/p/nut/nuTilda policy |
|---|---|---|
| root_symmetry | `['root_symmetry']` | `symmetryPlane` for all fields |
| solid walls | `['airfoil_upper', 'airfoil_lower', 'physical_tip', 'te_wall']` | `noSlip`, `zeroGradient`, wall function, `nuTilda fixedValue 0` |
| flow boundaries | `['outlet', 'farfield']` | `{'outlet': {'U': 'inletOutlet', 'p': 'fixedValue', 'nut': 'calculated', 'nuTilda': 'inletOutlet'}, 'farfield': {'U': 'freestreamVelocity', 'p': 'freestreamPressure', 'nut': 'calculated', 'nuTilda': 'freestream'}}` |

- force groups: `{'primary': ['airfoil_upper', 'airfoil_lower'], 'total': ['airfoil_upper', 'airfoil_lower', 'physical_tip', 'te_wall'], 'physical_tip': ['physical_tip'], 'te_wall': ['te_wall']}`
