# Failure Margin Report

Fixed-design load factor estimates are linearly scaled from the selected 2g structural run. This is appropriate for a first-pass beam-line check, but not a nonlinear aeroelastic or composite-joint proof.

| n | failure index | buckling index | tip defl m | wire tension N | wire margin N | root Fz est N | root M est N m |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.00 | -0.8210 | -0.9193 | 0.7716 | 1512.0 | 3069.4 | 398.6 | 2708.3 |
| 1.50 | -0.7314 | -0.8790 | 1.1574 | 2268.1 | 2313.4 | 597.9 | 4062.5 |
| 1.75 | -0.6867 | -0.8588 | 1.3503 | 2646.1 | 1935.4 | 697.6 | 4739.5 |
| 2.00 | -0.6419 | -0.8387 | 1.5432 | 3024.1 | 1557.4 | 797.2 | 5416.6 |

Estimated first-fail mode: `wire` at `n=3.030`.

Failure classification: wire tension controls the first-fail extrapolation for this candidate; deflection is next. Tube stress and shell buckling have materially larger extrapolated margins in this internal model.

- FEM scale check: internal reference tip `1.5432 m`, CalculiX max tip `0.0796 m`, mismatch `94.8%`

Because the local B32R deck displacement scale disagrees with the internal model, the first-fail value remains an internal screening estimate rather than a FEM-supported failure margin.
