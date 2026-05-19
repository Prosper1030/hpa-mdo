# Half-Wing Solver Stability Report

No corrected half-wing force-runaway values are accepted aerodynamic results.

| case | iterations | stable | CD_primary | CL_primary | driver | first unstable field | notes |
|---|---:|---|---:|---:|---|---|---|
| `halfwing_contaminated_noslip_root_short` | `80` | `False` | `0.02967517` | `0.4784893` | `pressure-driven` | `Ux` | Short replay reproduced the old noSlip-root setup; startup overshoot damps by iteration 80, and the existing 500-step contaminated run remains numerically stable but physically invalid. |
| `halfwing_corrected_previous_linearUpwind` | `88` | `False` | `None` | `None` | `not_reconstructable_from_summary` | `not_reconstructable_from_summary` | Historical bounded attempt from the current domain-convention bundle. |
| `halfwing_corrected_previous_conservative_same_schemes` | `54` | `False` | `None` | `None` | `not_reconstructable_from_summary` | `not_reconstructable_from_summary` | Historical bounded attempt from the current domain-convention bundle. |
| `halfwing_corrected_previous_bounded_upwind` | `36` | `False` | `1.889339` | `6.774819` | `pressure-driven` | `Uy` | Existing third corrected attempt; final values are diagnostic only and not accepted. |
| `halfwing_corrected_potential_init_attempt` | `120` | `False` | `0.03746052` | `0.09489149` | `pressure-driven` | `nuTilda` | Fourth corrected half-wing diagnostic attempt; finite at 120 iterations but not an accepted stable 500-step route-smoke. |

Engineering read:
- The old noSlip-root convention is numerically stable but physically contaminated by a wall at the centerline/root plane.
- The corrected root-symmetry cases repeatedly show pressure-dominated force runaway, so this is not a missing BC dictionary problem.
- Passing `checkMesh` and dry-run only proves setup readability; it does not make the corrected coefficients valid CFD.
