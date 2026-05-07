# Proxy vs Real Model Comparison

The Phase 9 proxy mass and deflection numbers are warning-only. Phase 10 uses the real dual-beam solver, but still through an adapter with explicit structural assumptions.

| recipe | proxy tip m | real tip m | proxy jig tip m | real jig tip m | proxy mass kg | real mass kg | comparability |
|---|---:|---:|---:|---:|---:|---:|---|
| proxy_selected_equal_CF_STD_100x98 | 2.286 | 0.378 | -1.235 | 0.672 | 32.959 | 32.959 | same nominal full-span two-tube catalog mass basis |
| production_split_main100_rear80 | 2.286 | 0.472 | -1.235 | 0.579 | 32.959 | 29.687 | not directly comparable: different assumed main/rear tube recipe |
| phase9_nominal_taper_70_40 | 2.286 | 3.017 | -1.235 | -1.967 | 32.959 | 11.079 | not directly comparable: different assumed main/rear tube recipe |
| geometry_rule_main100_rear50 | 2.286 | 0.622 | -1.235 | 0.428 | 32.959 | 24.671 | not directly comparable: different assumed main/rear tube recipe |
