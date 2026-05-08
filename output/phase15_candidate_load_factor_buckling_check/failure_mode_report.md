# Failure Mode Report

Candidate: `current_avl_compromise_conservative_closed`

## Direct Answers

- 1.5G internal fixed-design modeled limits clear: yes
- 1.75G internal fixed-design modeled limits clear: yes
- Estimated first-fail load factor: `n = 3.030`
- First failure mode: `wire_tension` (lift-wire tension reaches allowable).
- Buckling status: internal/local estimate only. This does not close full-wing global buckling, rear-spar/rib bracing, root fitting, wire attach, or termination strength.

## Evidence Basis

- Repaired candidate-equivalent FEM agreement through 2.0G: tip `3.74%`, wire reaction `2.09%`, root reaction `4.60%`.
- Corrected structured S4 shell route: B2 tapered tube error `2.41%`, B5 torsion error `0.07%`.
- 2.5G and 3.0G rows are fixed-design internal linear extrapolations beyond the checked repaired FEM range.

## Load-Factor Table

| n | tip defl m | loaded main tip z m | clearance m | root Fz N | root M N m | wire util | stress util | buckling util | first mode |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1.00 | 0.772 | 1.649 | 0.054 | -4.58 | 2708.3 | 0.330 | 0.179 | 0.081 | none_with_margin |
| 1.50 | 1.157 | 2.175 | 0.059 | -6.88 | 4062.5 | 0.495 | 0.269 | 0.121 | none_with_margin |
| 1.75 | 1.350 | 2.437 | 0.062 | -8.02 | 4739.5 | 0.578 | 0.313 | 0.141 | none_with_margin |
| 2.00 | 1.543 | 2.700 | 0.065 | -9.17 | 5416.6 | 0.660 | 0.358 | 0.161 | none_with_margin |
| 2.50 | 1.929 | 3.225 | 0.071 | -11.46 | 6770.8 | 0.825 | 0.448 | 0.202 | none_with_margin |
| 3.00 | 2.315 | 3.751 | 0.077 | -13.75 | 8124.9 | 0.990 | 0.537 | 0.242 | wire_tension_near_limit |

## Engineering Readout

- CFRP global bending stress stays below the internal beam-line allowable through 3.0G.
- Local tube wall buckling is not controlling in the current internal estimate, but the maximum D/t is high enough that ovalization and clamp-induced local wall buckling remain real hardware risks.
- Torsion/twist is below the configured internal twist limit in this fixed-design estimate; aeroelastic twist coupling is not signed off.
- Wire tension is the practical limiter: 3.0G is technically below the computed allowable but has only a small margin.
- Root joint, wire attach, and rib load-transfer are warnings, not validated failure modes. The report should not be used as a drawing-release signoff for fittings.
