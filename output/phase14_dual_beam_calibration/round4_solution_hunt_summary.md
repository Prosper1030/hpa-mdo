# Round 4 Solution Hunt Summary

## Scope

Round 4 focused on the two remaining structural warning topics in the Mac-local CalculiX parity ladder:

- `B2`: tapered single-pipe cantilever stiffness gap
- `B5`: torque ownership / observability for direct `MY` versus the front/rear force-couple surrogate

## Outcomes

| Topic | Outcome | Engineering judgment |
| --- | --- | --- |
| `B2` tapered tube | `WARN` | No legal CalculiX `PIPE` route in this hunt reduced the persistent `10%` to `12%` stiffness bias. Midpoint/average-geometry sampling stayed in the same band, and `B31R/B31/B32` pipe swaps were solver-rejected because `SECTION=PIPE` is restricted to `B32R`. |
| `B5` direct `MY` | `OBSERVABLE` | `SECTION FORCES` exposes a clean main-beam torque signal. In the dual-beam benchmark, the direct `MY` case shows `38.334 N m` root section torque versus `38.333 N m` expected from the distributed nodal `MY` loads (`0.001%` error). |
| `B5` front/rear vertical couple | `SURROGATE_ONLY` | The force-couple route still changes the centerline `UZ` twist proxy, but beam-axis section torque stays near zero on both beams. In this linked dual-beam topology it behaves like a coupled bending/shear surrogate, not the same truth observable as direct `MY`. |

## Trust Policy

1. `B1`: trusted linear beam sanity gate.
2. `B2`: keep as `WARN` until the APDL truth deck is checked.
3. `B3`: trusted linear no-wire dual-beam displacement gate.
4. `B4`: trusted as an APDL-style vertical-wire surrogate with corrected reaction bookkeeping.
5. `B5`: split the policy.
   Direct `MY` ownership is now auditable in CalculiX through `SECTION FORCES`.
   The front/rear vertical-couple case should remain a separate surrogate experiment, not a truth-equivalent replacement.

## Artifacts

- `b2_solution_hunt.csv` / `b2_solution_hunt.md`
- `b5_single_beam_torsion_probe.csv` / `b5_single_beam_torsion_probe.md`
- `b5_solution_hunt.csv` / `b5_solution_hunt.md`
- `apdl_truth_decks/b2_tapered_tube.apdl`
- `apdl_truth_decks/b5_main_beam_my_about_main_spar.apdl`
- `apdl_truth_decks/b5_front_rear_vertical_couple.apdl`
- `apdl_truth_decks/b5_cm_off_control.apdl`

## Bottom Line

The round-4 hunt did not clear `B2`, but it did resolve the core `B5` observability question. From a structures-engineering standpoint, the remaining risk is no longer “CalculiX cannot show torque”; it is that the vertical-couple surrogate is not the same physical truth path as direct beam-axis `MY`.
