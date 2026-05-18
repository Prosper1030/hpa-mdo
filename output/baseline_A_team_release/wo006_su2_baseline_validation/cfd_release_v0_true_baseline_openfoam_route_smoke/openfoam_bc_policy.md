# OpenFOAM Boundary-Condition Policy

- solver: `simpleFoam`
- turbulence model: `SpalartAllmaras`
- AoA: `0.18 deg`; U/dragDir/liftDir rotated consistently
- tips: `tip_left` and `tip_right` are physical full-wing tips, so they are noSlip walls, not symmetry planes

| patch | role | U | p | nut | nuTilda | generated boundary class |
|---|---|---|---|---|---|---|
| `airfoil_upper` | wall | `noSlip` | `zeroGradient` | `nutUSpaldingWallFunction` | `fixedValue 0` | `wall` |
| `airfoil_lower` | wall | `noSlip` | `zeroGradient` | `nutUSpaldingWallFunction` | `fixedValue 0` | `wall` |
| `te_wall` | wall | `noSlip` | `zeroGradient` | `nutUSpaldingWallFunction` | `fixedValue 0` | `wall` |
| `outlet` | flow boundary | `inletOutlet` | `fixedValue` | `calculated` | `inletOutlet` | `patch` |
| `farfield` | flow boundary | `freestreamVelocity` | `freestreamPressure` | `calculated` | `freestream` | `patch` |
| `tip_left` | wall | `noSlip` | `zeroGradient` | `nutUSpaldingWallFunction` | `fixedValue 0` | `wall` |
| `tip_right` | wall | `noSlip` | `zeroGradient` | `nutUSpaldingWallFunction` | `fixedValue 0` | `wall` |

No `k`/`omega` fields are used because this case uses Spalart-Allmaras (`nuTilda`).
