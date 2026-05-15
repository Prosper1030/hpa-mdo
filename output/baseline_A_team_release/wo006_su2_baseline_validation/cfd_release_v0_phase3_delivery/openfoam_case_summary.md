# OpenFOAM Case Summary

Route: `OpenFOAM local full-wing external-aero CFD`

- solver: `simpleFoam`
- turbulence model: `SpalartAllmaras`
- U: `6.5` m/s
- AOA: `0.0` deg
- layer schedule: `[0, 3, 8]`
- OpenFOAM wrapper: `/opt/homebrew/bin/openfoam`

| case | requested layers | status | cells | checkMesh |
|---|---:|---|---:|---|
| `layers_0` | `0` | `route_smoke_case_completed` | `212987` | `pass` |
| `layers_3` | `3` | `mesh_quality_failed` | `232934` | `fail` |
| `layers_8` | `8` | `route_smoke_case_completed` | `238014` | `pass` |

The case files under `openfoam_cases/` are the rerunnable route artifact.
