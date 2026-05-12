# Baseline A Mass / CG / Margin Daily Review

Ledger verdict: `mass_cg_authority_bounded_wo006_ready`

| Review item | Current read | 30-minute decision |
|---|---|---|
| Design mass authority | 98.5 kg | Use as current design gross mass unless user changes it |
| Suspect P1 screening aggregate | 106.828608 kg | Do not use as current design mass truth |
| Managed CG | 0.75 m | Accepted screening row |
| Uncompensated CG | 0.780039 m | Rejected; keep rebalance requirement visible |
| Rebalance | 0.057304 m forward on 56 kg | Inside screening limit |
| C04 original peel | margin -0.893 | Fail evidence must stay visible |
| C04 installed fix | governing margin 0.8876 | Proceed to coupon/local FEM, not build sign-off |
| Static margin | 0.092835 | Tail trim/stability `pass` at managed CG |
| Bounded twist | 1.906952 deg | Screening pass; direct stress-test remains warning |
| Tail power charge | 13.33234 W | Power budget placeholder, not QPROP/XROTOR result |
| QPROP/XROTOR | independent lane | Do not use it to pass/fail C04 or rib blockers |

Next review focus: WO-006 after data-authority restoration as bounded aero calibration using 98.5 kg and current pipeline span authority. WO-005 remains draft-only; RFQ, procurement, release, and final sign-off remain blocked.
