# Medium Final Window Stability

- accepted final-100 force gate at 2000: `True`
- accepted including residual/yPlus checks: `True`

## Checkpoint Ladder

| checkpoint | CD_total_physical drift | CD_primary drift | CL_primary drift | CmPitch drift | accepted |
|---:|---:|---:|---:|---:|---|
| 500 | 6.159% | 6.144% | 4.571% | 3.381% | `False` |
| 1000 | 6.109% | 6.093% | 2.602% | 1.522% | `False` |
| 1500 | 2.467% | 2.445% | 1.276% | 0.987% | `False` |
| 2000 | 0.583% | 0.575% | 0.398% | 0.475% | `True` |

## Final-100 Gate at 2000

| quantity | final-100 drift | threshold | pass |
|---|---:|---:|---|
| `CD_total_physical` | 0.583% | 1.000% | `True` |
| `CD_primary` | 0.575% | 1.000% | `True` |
| `CL_primary` | 0.398% | 0.500% | `True` |
| `CmPitch_primary` | 0.475% | 1.000% | `True` |

## Raw Final Windows

- primary final-100: `{"Cd": {"last": 0.03369494, "max": 0.03388918, "mean": 0.0337870492, "min": 0.03369494, "relative_span": 0.005748948327810713, "span": 0.0001942399999999983}, "Cl": {"last": 1.158639, "max": 1.158639, "mean": 1.15643894, "min": 1.154037, "relative_span": 0.0039794578345831175, "span": 0.004601999999999995}, "CmPitch": {"last": -0.1313859, "max": -0.1307626, "mean": -0.13108485900000003, "min": -0.1313859, "relative_span": 0.004754935121835797, "span": 0.0006232999999999933}, "rows": 100, "status": "available", "window": 100}`
- total_physical final-100: `{"Cd": {"last": 0.03375281, "max": 0.0339501, "mean": 0.03384637050000001, "min": 0.03375281, "relative_span": 0.005828985415142098, "span": 0.0001972899999999958}, "Cl": {"last": 1.158631, "max": 1.158631, "mean": 1.1564310800000004, "min": 1.154029, "relative_span": 0.00397948488205626, "span": 0.004601999999999995}, "CmPitch": {"last": -0.131313, "max": -0.1306888, "mean": -0.13101151799999994, "min": -0.131313, "relative_span": 0.004764466586823454, "span": 0.0006242000000000192}, "rows": 100, "status": "available", "window": 100}`
