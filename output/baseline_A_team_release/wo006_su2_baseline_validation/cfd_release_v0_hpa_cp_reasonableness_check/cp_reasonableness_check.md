# WO-006 Fine Cp reasonableness check

This diagnostic extracts OpenFOAM Cp from the accepted Fine saved pressure field on
the primary airfoil surfaces and compares each station with local XFOIL Cp at
matched OpenFOAM pressure-sectional lift.

## Station comparison

| station | eta | OF clp | OF cdp | OF upper Cpmin | XFOIL upper Cpmin | OF aft upper Cp | XFOIL aft upper Cp | OF TE dCp | XFOIL TE dCp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| root_eta0p10 | 0.10 | 1.231 | 0.0279 | -1.721 | -1.584 | -0.299 | -0.297 | 0.192 | 0.076 |
| mid_eta0p50 | 0.50 | 1.300 | 0.0280 | -1.708 | -1.717 | -0.302 | -0.297 | 0.183 | 0.080 |
| outboard_eta0p80 | 0.80 | 0.810 | 0.0036 | -1.469 | -1.471 | -0.021 | 0.017 | 0.095 | 0.060 |

## Largest net pressure-drag regions

| span region | chord region | CDp global | CLp global |
|---|---|---:|---:|
| mid_0p25_0p65 | aft_0p60_0p90 | 0.024076 | 0.090159 |
| mid_0p25_0p65 | mid_0p20_0p60 | 0.021776 | 0.264828 |
| root_0p00_0p25 | aft_0p60_0p90 | 0.017452 | 0.065127 |
| root_0p00_0p25 | mid_0p20_0p60 | 0.016066 | 0.192453 |
| outboard_0p65_0p90 | mid_0p20_0p60 | 0.010106 | 0.101247 |
| outboard_0p65_0p90 | aft_0p60_0p90 | 0.004999 | 0.024108 |
| tip_0p90_1p00 | mid_0p20_0p60 | 0.003129 | 0.023862 |
| mid_0p25_0p65 | TE_0p90_1p00 | 0.002478 | 0.010237 |

## Largest positive pressure-drag regions

| span region | chord region | surface | CDp global | mean Cp |
|---|---|---|---:|---:|
| mid_0p25_0p65 | mid_0p20_0p60 | upper | 0.018793 | -1.192 |
| mid_0p25_0p65 | aft_0p60_0p90 | upper | 0.018545 | -0.438 |
| root_0p00_0p25 | mid_0p20_0p60 | upper | 0.013838 | -1.201 |
| root_0p00_0p25 | aft_0p60_0p90 | upper | 0.013398 | -0.437 |
| outboard_0p65_0p90 | mid_0p20_0p60 | upper | 0.009217 | -0.944 |
| mid_0p25_0p65 | LE_0p00_0p20 | lower | 0.006638 | 0.480 |
| mid_0p25_0p65 | aft_0p60_0p90 | lower | 0.005531 | 0.316 |
| root_0p00_0p25 | LE_0p00_0p20 | lower | 0.004836 | 0.483 |
