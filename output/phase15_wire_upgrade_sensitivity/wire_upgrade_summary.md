# Wire Upgrade Summary

Candidate: `current_avl_compromise_conservative_closed`

## Direct Answer

- Does upgrading wire remove the current first-fail blocker? `yes`, once the modeled allowable is at least about `5 kN`; the next fixed-design limiter becomes `tip_deflection`, not CFRP stress or shell buckling.
- Current first fail: `wire_tension` at `n = 3.030`.
- Next failure mode after wire: `tip_deflection` at `n = 3.305`.
- `1.75G` remains safe for every swept allowable case.
- `3.0G` becomes comfortable in wire utilization at `6 kN` allowable and above, but the whole system still has only moderate reserve because tip deflection is estimated to limit at about `3.305G`.

## Sweep

| allowable case | allowable kN | T 1.0G N | util 1.0G | T 1.5G N | util 1.5G | T 1.75G N | util 1.75G | T 2.0G N | util 2.0G | T 3.0G N | util 3.0G | first fail n | first mode | 1.75G safe | 3.0G comfortable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| current | 4.581 | 1512.0 | 0.330 | 2268.1 | 0.495 | 2646.1 | 0.578 | 3024.1 | 0.660 | 4536.1 | 0.990 | 3.030 | wire_tension | yes | no |
| 5kN | 5.000 | 1512.0 | 0.302 | 2268.1 | 0.454 | 2646.1 | 0.529 | 3024.1 | 0.605 | 4536.1 | 0.907 | 3.305 | tip_deflection | yes | no |
| 6kN | 6.000 | 1512.0 | 0.252 | 2268.1 | 0.378 | 2646.1 | 0.441 | 3024.1 | 0.504 | 4536.1 | 0.756 | 3.305 | tip_deflection | yes | yes |
| 8kN | 8.000 | 1512.0 | 0.189 | 2268.1 | 0.284 | 2646.1 | 0.331 | 3024.1 | 0.378 | 4536.1 | 0.567 | 3.305 | tip_deflection | yes | yes |
| 10kN | 10.000 | 1512.0 | 0.151 | 2268.1 | 0.227 | 2646.1 | 0.265 | 3024.1 | 0.302 | 4536.1 | 0.454 | 3.305 | tip_deflection | yes | yes |

## Current Wire Source

- Material key: `dyneema_sk75`.
- Diameter: `2.500 mm`.
- Area: `4.909 mm^2`.
- Material tensile strength in local database: `3500.0 MPa`.
- Current policy: max tension fraction `0.400` and material safety factor `1.500`.
- Formula allowable: `4581.5 N`; artifact allowable: `4581.5 N`; delta `0.00%`.
- Artifact source: `/Volumes/Samsung SSD/hpa-mdo/output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_closure/runs/conservative_best/structure_response/lift_wire_rigging.json`.
- Implied published/minimum break load to justify the current artifact under the same policy: `17.18 kN`.

## FEM / Blocking Readout

- This package changes only the allowable tension in the failure accounting. It does not redesign the wing, change airfoils, or change aero ranking.
- The repaired candidate-equivalent FEM route is still the validation basis through 2.0G. The 3.0G wire sensitivity is a fixed-design linear load extrapolation.
- Because geometry and load path are unchanged, this is the right quick check for whether wire allowable is the blocker. A final upgraded-wire signoff still needs a Mac-local FEM rerun with the actual wire stiffness, pretension, attach hardware, and candidate-specific local joint shell/detail model.

## Engineering Judgment

- A stronger wire does remove the current wire-tension first-fail blocker numerically.
- It does not make the candidate a clean 3.0G design in the submission sense: tip deflection becomes the next limiter at about 3.305G, and the wire attach/root joint/rib load transfer remain unresolved hardware details.
- The current modeled 2.5 mm Dyneema allowable should be treated as a model-derived material allowable, not as proof that any off-the-shelf 2.5 mm cord is acceptable.
- First useful upgrade target: `5kN` allowable. Practical recommendation is still to buy/spec by published minimum breaking load, not by nominal diameter.
