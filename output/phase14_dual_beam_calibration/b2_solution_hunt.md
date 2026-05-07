# B2 Solution Hunt

## Candidate Summary

| Candidate | Status | Element | Sampling | Tip [m] | Reference [m] | Ref vs CCX [%] |
| --- | --- | --- | --- | ---: | ---: | ---: |
| current_b32r_pipe | WARN | B32R | current | 0.160448 | 0.179514 | 10.620968 |
| midpoint_b32r_pipe | WARN | B32R | midpoint | 0.163630 | 0.183077 | 10.622369 |
| average_geometry_b32r_pipe | WARN | B32R | average_geometry | 0.163630 | 0.183077 | 10.622369 |
| b31r_pipe_probe | REJECTED | B31R | current |  |  |  |
| b31_pipe_probe | REJECTED | B31 | current |  |  |  |
| b32_pipe_probe | REJECTED | B32 | current |  |  |  |
| apdl_truth_deck | TRUTH_DECK_PREPARED | BEAM188 | current |  |  |  |

## Engineering Interpretation

- The current legal CalculiX route stays at 10.621% error relative to the independent reference; midpoint and average-geometry sampling stay at 10.622% / 10.622%, so the warning does not come from a simple elementwise section-sampling choice.
- CalculiX 2.23 rejects the obvious element-type swap probes (`B31R`, `B31`, `B32`) because `*BEAM SECTION, SECTION=PIPE` is restricted to `B32R`. That removes the most obvious like-for-like pipe sensitivity path.
- No honest Mac-local CalculiX route in this hunt moved B2 into a pass-grade band without changing the physics family or using a manual-invalid workaround.
- The next defensible truth source is the APDL deck at `/Volumes/Samsung SSD/hpa-mdo/output/phase14_dual_beam_calibration/apdl_truth_decks/b2_tapered_tube.apdl`. It keeps the same beam/load conventions while moving the tapered-pipe question to BEAM188/CTUBE.

## Verdict

B2 remains a warning in the current CalculiX gate. From a structures-engineering standpoint, the evidence now points to a solver/formulation difference for tapered pipe beams rather than a trivial local exporter bug.
