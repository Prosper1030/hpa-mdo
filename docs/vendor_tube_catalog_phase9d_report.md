# Phase 9d Vendor-Aware Tube Catalog Report

## Scope
- Starting from the existing `data/carbon_tubes.csv` seed catalog, Phase 9d augments missing SKUs with explicitly flagged hypothetical generic vendor rows so that the current Pareto representatives can all be discretized.
- Catalog used for this run: `/Volumes/Samsung SSD/hpa-mdo/output/vendor_tube_catalog_phase9d/hypothetical_vendor_catalog.csv` (22 base rows + 64 hypothetical infill rows).
- Selection rule: same material key, conservative snap-up on OD and wall thickness, then minimize vendor mass per meter, then vendor cost.

## Design Summary

| Role | Layout | Mult | Flight Mass (kg) | Tube Mass Cont. (kg) | Tube Mass Vendor (kg) | Delta (kg) | Delta (%) | Tube Cost (USD) | Clearance (mm) | Wire Margin (N) |
|------|--------|------|------------------|-----------------------|------------------------|------------|-----------|-----------------|----------------|-----------------|
| mass_first | single | 5.000 | 11.954 | 9.448 | 12.252 | +2.804 | +29.68 | 2851.6 | 5.588 | 2930.9 |
| balanced | single | 2.000 | 14.813 | 12.334 | 16.150 | +3.817 | +30.94 | 3382.1 | 1.492 | 3177.2 |
| aero_first | single | 1.000 | 24.970 | 22.522 | 30.283 | +7.760 | +34.46 | 4329.8 | 0.000 | 3800.9 |
| dual_anchor | dual | 1.000 | 20.389 | 17.879 | 27.487 | +9.608 | +53.74 | 3949.4 | 0.000 | 4336.3 |

## Segment Selections

| Role | Spar | Seg | Req OD (mm) | Req t (mm) | Selected SKU | Selected OD x t (mm) | Hypothetical | Margin OD / t (mm) | Full-Wing Qty | Full-Wing Cost (USD) |
|------|------|-----|-------------|------------|--------------|----------------------|--------------|--------------------|---------------|----------------------|
| mass_first | main | 1 | 61.270 | 0.800 | CF-HM-65x63 | 65.0 x 1.0 | yes | +3.730 / +0.200 | 1 | 191.2 |
| mass_first | main | 2 | 61.270 | 0.800 | CF-HM-65x63 | 65.0 x 1.0 | yes | +3.730 / +0.200 | 2 | 382.3 |
| mass_first | main | 3 | 61.270 | 0.800 | CF-HM-65x63 | 65.0 x 1.0 | yes | +3.730 / +0.200 | 2 | 382.3 |
| mass_first | main | 4 | 61.270 | 0.800 | CF-HM-65x63 | 65.0 x 1.0 | yes | +3.730 / +0.200 | 2 | 382.3 |
| mass_first | main | 5 | 45.950 | 0.800 | CF-HM-50x48 | 50.0 x 1.0 | no | +4.050 / +0.200 | 2 | 300.0 |
| mass_first | main | 6 | 30.000 | 0.800 | CF-HM-30x28 | 30.0 x 1.0 | yes | +0.000 / +0.200 | 2 | 224.8 |
| mass_first | rear | 1 | 20.000 | 0.800 | CF-HM-20x18 | 20.0 x 1.0 | yes | +0.000 / +0.200 | 1 | 89.9 |
| mass_first | rear | 2 | 20.000 | 0.800 | CF-HM-20x18 | 20.0 x 1.0 | yes | +0.000 / +0.200 | 2 | 179.8 |
| mass_first | rear | 3 | 20.000 | 0.800 | CF-HM-20x18 | 20.0 x 1.0 | yes | +0.000 / +0.200 | 2 | 179.8 |
| mass_first | rear | 4 | 20.000 | 0.800 | CF-HM-20x18 | 20.0 x 1.0 | yes | +0.000 / +0.200 | 2 | 179.8 |
| mass_first | rear | 5 | 20.000 | 0.800 | CF-HM-20x18 | 20.0 x 1.0 | yes | +0.000 / +0.200 | 2 | 179.8 |
| mass_first | rear | 6 | 20.000 | 0.800 | CF-HM-20x18 | 20.0 x 1.0 | yes | +0.000 / +0.200 | 2 | 179.8 |
| balanced | main | 1 | 67.780 | 0.800 | CF-HM-70x68 | 70.0 x 1.0 | yes | +2.220 / +0.200 | 1 | 202.4 |
| balanced | main | 2 | 67.780 | 0.800 | CF-HM-70x68 | 70.0 x 1.0 | yes | +2.220 / +0.200 | 2 | 404.8 |
| balanced | main | 3 | 67.780 | 0.800 | CF-HM-70x68 | 70.0 x 1.0 | yes | +2.220 / +0.200 | 2 | 404.8 |
| balanced | main | 4 | 67.780 | 0.800 | CF-HM-70x68 | 70.0 x 1.0 | yes | +2.220 / +0.200 | 2 | 404.8 |
| balanced | main | 5 | 60.204 | 0.800 | CF-HM-65x63 | 65.0 x 1.0 | yes | +4.796 / +0.200 | 2 | 382.3 |
| balanced | main | 6 | 52.317 | 0.800 | CF-HM-55x53 | 55.0 x 1.0 | yes | +2.683 / +0.200 | 2 | 337.3 |
| balanced | rear | 1 | 22.398 | 0.800 | CF-HM-25x23 | 25.0 x 1.0 | yes | +2.602 / +0.200 | 1 | 101.1 |
| balanced | rear | 2 | 22.398 | 0.800 | CF-HM-25x23 | 25.0 x 1.0 | yes | +2.602 / +0.200 | 2 | 202.3 |
| balanced | rear | 3 | 22.398 | 0.800 | CF-HM-25x23 | 25.0 x 1.0 | yes | +2.602 / +0.200 | 2 | 202.3 |
| balanced | rear | 4 | 22.398 | 0.800 | CF-HM-25x23 | 25.0 x 1.0 | yes | +2.602 / +0.200 | 2 | 202.3 |
| balanced | rear | 5 | 22.398 | 1.748 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.602 / +0.252 | 2 | 268.9 |
| balanced | rear | 6 | 22.398 | 1.748 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.602 / +0.252 | 2 | 268.9 |
| aero_first | main | 1 | 61.847 | 1.552 | CF-HM-65x61 | 65.0 x 2.0 | yes | +3.153 / +0.448 | 1 | 230.5 |
| aero_first | main | 2 | 61.847 | 1.552 | CF-HM-65x61 | 65.0 x 2.0 | yes | +3.153 / +0.448 | 2 | 461.0 |
| aero_first | main | 3 | 61.847 | 1.552 | CF-HM-65x61 | 65.0 x 2.0 | yes | +3.153 / +0.448 | 2 | 461.0 |
| aero_first | main | 4 | 61.847 | 1.552 | CF-HM-65x61 | 65.0 x 2.0 | yes | +3.153 / +0.448 | 2 | 461.0 |
| aero_first | main | 5 | 54.256 | 1.552 | CF-HM-55x51 | 55.0 x 2.0 | yes | +0.744 / +0.448 | 2 | 413.0 |
| aero_first | main | 6 | 46.352 | 1.552 | CF-HM-50x46 | 50.0 x 2.0 | no | +3.648 / +0.448 | 2 | 432.0 |
| aero_first | rear | 1 | 22.374 | 1.552 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.626 / +0.448 | 1 | 134.4 |
| aero_first | rear | 2 | 22.374 | 1.552 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.626 / +0.448 | 2 | 268.9 |
| aero_first | rear | 3 | 22.374 | 1.552 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.626 / +0.448 | 2 | 268.9 |
| aero_first | rear | 4 | 22.374 | 1.552 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.626 / +0.448 | 2 | 268.9 |
| aero_first | rear | 5 | 22.374 | 4.283 | CF-HM-25x15 | 25.0 x 5.0 | yes | +2.626 / +0.717 | 2 | 465.2 |
| aero_first | rear | 6 | 22.374 | 4.283 | CF-HM-25x15 | 25.0 x 5.0 | yes | +2.626 / +0.717 | 2 | 465.2 |
| dual_anchor | main | 1 | 69.848 | 1.329 | CF-HM-70x66 | 70.0 x 2.0 | yes | +0.152 / +0.671 | 1 | 242.5 |
| dual_anchor | main | 2 | 69.848 | 1.329 | CF-HM-70x66 | 70.0 x 2.0 | yes | +0.152 / +0.671 | 2 | 485.0 |
| dual_anchor | main | 3 | 69.848 | 1.329 | CF-HM-70x66 | 70.0 x 2.0 | yes | +0.152 / +0.671 | 2 | 485.0 |
| dual_anchor | main | 4 | 69.848 | 1.329 | CF-HM-70x66 | 70.0 x 2.0 | yes | +0.152 / +0.671 | 2 | 485.0 |
| dual_anchor | main | 5 | 54.528 | 1.329 | CF-HM-55x51 | 55.0 x 2.0 | yes | +0.472 / +0.671 | 2 | 413.0 |
| dual_anchor | main | 6 | 38.578 | 1.329 | CF-HM-40x36 | 40.0 x 2.0 | no | +1.422 / +0.671 | 2 | 360.0 |
| dual_anchor | rear | 1 | 22.400 | 1.329 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.600 / +0.671 | 1 | 134.4 |
| dual_anchor | rear | 2 | 22.400 | 1.329 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.600 / +0.671 | 2 | 268.9 |
| dual_anchor | rear | 3 | 22.400 | 1.329 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.600 / +0.671 | 2 | 268.9 |
| dual_anchor | rear | 4 | 22.400 | 1.329 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.600 / +0.671 | 2 | 268.9 |
| dual_anchor | rear | 5 | 22.400 | 1.329 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.600 / +0.671 | 2 | 268.9 |
| dual_anchor | rear | 6 | 22.400 | 1.329 | CF-HM-25x21 | 25.0 x 2.0 | yes | +2.600 / +0.671 | 2 | 268.9 |

## Findings

- The smallest catalog discretization penalty is `mass_first` at +2.804 kg versus the continuous tube ideal.
- The cheapest full-wing tube BOM is `mass_first` at 2851.6 USD.
- The largest vendor penalty appears on `dual_anchor` at +9.608 kg, which is the main warning sign if we later tighten the catalog to real SKUs.
- Hypothetical rows are concentrated in the smaller / thicker tubes that the current seed catalog does not cover, especially rear-spar heavy-wall segments and the 65-70 mm main-spar plateau region.
- This means the Phase 9 mainline can now reason about procurement-level discreteness without blocking on a real vendor scrape, while keeping every synthetic SKU explicitly traceable.

