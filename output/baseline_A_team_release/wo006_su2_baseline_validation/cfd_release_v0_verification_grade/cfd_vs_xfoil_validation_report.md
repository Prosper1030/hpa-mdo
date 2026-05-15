# CFD Vs XFOIL Validation Report

## Existing XFOIL / Spanwise-Integrated Reference

The existing screening estimate in `output/baseline_A_team_release/wo006_su2_baseline_validation/aero_model_delta_table.csv` is:

| source | value |
|---|---:|
| Tier2/XFOIL profile CD | `0.00936885` |
| CD0 total | `0.01325873` |
| AVL induced CDi | `0.0127613` |
| combined screening CD total | `0.02602003` |
| screening CL | `1.16853` |

## CFD Evidence Obtained Here

The closest strict snappy finite OpenFOAM run is `wall_resolved_target`, but it is not accepted because its yPlus and actual layer count fail. Its rejected high-yPlus values are `CD_primary=0.07326929`, `CL_primary=0.9215704`, `CD_total=0.07332259`.

## Validation Judgment

The CFD route does **not** support or contradict the XFOIL/spanwise-integrated estimate yet. It remains inconclusive. The rejected OpenFOAM high-yPlus coefficients are much higher than the screening `CD_total≈0.02602003`, but the near-wall treatment is not valid enough to use that difference as aerodynamic evidence.

Engineering interpretation: this work checks the exact right question and finds that the current open-source route has not earned the right to answer it. Do not replace the CFD gate with a new XFOIL budget, and do not treat the high-yPlus `CD≈0.07-0.09` OpenFOAM range as drag truth.
