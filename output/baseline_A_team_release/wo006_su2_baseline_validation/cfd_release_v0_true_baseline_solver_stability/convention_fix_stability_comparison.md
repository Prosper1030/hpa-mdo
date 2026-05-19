# Convention Fix Stability Comparison

- old contaminated noSlip-root run is numerically stable but physically invalid for corrected CD_total.
- corrected unstable half-wing run is diagnostic only; its force-runaway coefficients are not accepted.
- stable corrected route accepted: `True`
- stable route: `full-wing-mirror`
- stable CD_primary / CL_primary / CD_total: `0.03276165`, `1.133291`, `0.05708291`
- stable diagnostic CD sum/fraction: `0.0243212665`, `0.4260691422353906`
- stable yPlus: `{'count': 29952, 'max': 2.65697, 'mean': 0.5678595352296987, 'min': 0.0189722, 'p90': 0.8781874000000001, 'p95': 1.0904245, 'p99': 1.8354890999999969}`

Engineering read:
- Root contamination is removed only for the stable corrected/full-wing route, not for the old replay.
- Diagnostic CD should be small relative to total; if it dominates, the route remains blocked for sweep work.
- CL plausibility is a route-smoke sanity check only; this is still not grid-converged validation.
