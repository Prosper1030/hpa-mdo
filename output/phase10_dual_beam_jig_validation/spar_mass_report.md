# Spar Mass Report

This sidecar performs forward checks of assumed tube recipes. It does not solve an inverse required-EI sizing problem; root/tip EI values are reported in `dual_beam_validation_results.csv` and `required_EI_basis=not_computed_forward_recipe_check_only`.

| case | recipe | spar tube mass kg | target kg | margin kg | failure index | status |
|---|---|---:|---:|---:|---:|---|
| smooth_tier2_production_baseline | proxy_selected_equal_CF_STD_100x98 | 32.959 | 11.753 | -21.206 | -0.959 | not_cleared_under_adapter_assumptions |
| smooth_tier2_production_baseline | production_split_main100_rear80 | 29.687 | 11.753 | -17.933 | -0.948 | not_cleared_under_adapter_assumptions |
| smooth_tier2_production_baseline | phase9_nominal_taper_70_40 | 11.079 | 11.753 | 0.674 | -0.681 | not_cleared_under_adapter_assumptions |
| smooth_tier2_production_baseline | geometry_rule_main100_rear50 | 24.671 | 11.753 | -12.918 | -0.925 | not_cleared_under_adapter_assumptions |
| old_fx_clark_baseline | proxy_selected_equal_CF_STD_100x98 | 31.680 | 11.753 | -19.927 | -0.953 | not_cleared_under_adapter_assumptions |
| old_fx_clark_baseline | production_split_main100_rear80 | 28.535 | 11.753 | -16.781 | -0.940 | not_cleared_under_adapter_assumptions |
| old_fx_clark_baseline | phase9_nominal_taper_70_40 | 10.649 | 11.753 | 1.104 | -0.645 | not_cleared_under_adapter_assumptions |
| old_fx_clark_baseline | geometry_rule_main100_rear50 | 23.714 | 11.753 | -11.961 | -0.918 | not_cleared_under_adapter_assumptions |
