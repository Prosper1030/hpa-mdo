# Fine Final Window Stability

- accepted final-100 force gate at 2000: `True`
- accepted including residual/yPlus checks: `True`

## Checkpoint Ladder

| checkpoint | CD_total_physical drift | CD_primary drift | CL_primary drift | CmPitch drift | accepted |
|---:|---:|---:|---:|---:|---|
| 500 | 3.791% | 3.752% | 4.067% | 3.296% | `False` |
| 1000 | 6.209% | 6.185% | 3.269% | 2.192% | `False` |
| 1500 | 2.211% | 2.192% | 1.187% | 1.084% | `False` |
| 2000 | 0.524% | 0.518% | 0.326% | 0.409% | `True` |

## Final-100 Gate at 2000

| quantity | final-100 drift | threshold | pass |
|---|---:|---:|---|
| `CD_total_physical` | 0.524% | 1.000% | `True` |
| `CD_primary` | 0.518% | 1.000% | `True` |
| `CL_primary` | 0.326% | 0.500% | `True` |
| `CmPitch_primary` | 0.409% | 1.000% | `True` |

## Raw Final Windows

- primary final-100: `{"Cd": {"last": 0.03320877, "max": 0.03338132, "mean": 0.03329079700000001, "min": 0.03320877, "relative_span": 0.005183114120097528, "span": 0.00017255000000000048}, "Cl": {"last": 1.160934, "max": 1.160934, "mean": 1.1591328200000002, "min": 1.157156, "relative_span": 0.0032593331280187862, "span": 0.003777999999999837}, "CmPitch": {"last": -0.1322822, "max": -0.1317425, "mean": -0.132023263, "min": -0.1322822, "relative_span": 0.004087915930391573, "span": 0.0005396999999999763}, "rows": 100, "status": "available", "window": 100}`
- total_physical final-100: `{"Cd": {"last": 0.03326556, "max": 0.03344034, "mean": 0.0333486457, "min": 0.03326556, "relative_span": 0.005240992440061798, "span": 0.00017477999999999938}, "Cl": {"last": 1.160927, "max": 1.160927, "mean": 1.1591249699999997, "min": 1.157148, "relative_span": 0.003260217921109902, "span": 0.003778999999999977}, "CmPitch": {"last": -0.1322138, "max": -0.1316734, "mean": -0.13195454100000004, "min": -0.1322138, "relative_span": 0.004095349776556733, "span": 0.0005403999999999964}, "rows": 100, "status": "available", "window": 100}`
