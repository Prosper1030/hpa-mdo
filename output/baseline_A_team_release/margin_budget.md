# Baseline A Mass / CG / Margin Budget

Verdict: `mass_cg_margin_ledger_ready`

This ledger is the central screening truth surface for Baseline A mass, CG, drag/power charge, and governing margins. It is not measured aircraft weight and balance and not final aircraft sign-off.

## Mass and CG

| Quantity | Value | Status |
|---|---:|---|
| Gross screening mass | 106.828608 kg | estimate |
| Computed uncompensated CG | 0.780039 m | explicitly_rejected |
| Managed screening CG | 0.75 m | managed_final_cg_pass |
| Required forward rebalance | 0.057304 m on 56 kg equivalent mass | screening |

## Component Ledger

| Component | kg | x m | confidence | CG | drag | power | structure |
|---|---:|---:|---|---|---|---|---|
| base_aircraft_pilot_screening_mass | 96 | 0.72 | estimate | yes | no | yes | yes |
| selected_tail_screening_delta | 1.172727 | 8.31 | estimate | yes | yes | yes | yes |
| fast_design_loop_selected_rib_pack | 5.715042 | 0.461633 | estimate | yes | no | yes | yes |
| p1_c04_saddle_ring_yoke_clamp_pair | 0.093839 | 0.562799 | estimate | yes | no | yes | yes |
| spar_splice_transport_joint_pack | 3.847 | 0.461151 | estimate | yes | no | yes | yes |

## Margin Summary

| Gate | Current value | Read |
|---|---:|---|
| C04 original eccentric peel | -0.893 | fail evidence retained |
| Installed saddle/yoke/clamp governing margin | 0.8876 | screening pass, coupon/local FEM required |
| Saddle-ring yoke adhesive shear margin | 65.0672 | not governing in fast model |
| Static margin at managed CG | 0.092835 | tail trim/stability `pass` |
| Bounded physical twist | 1.906952 deg | below 3 deg screening bound |
| Direct spar-pair stress-test | 3.177742 deg | conservative mapping warning, not aero-surface sign-off |
| Root bending ratio | 0.97159 | inside screening relaxation bounds |
| Structural hardware mass delta | 3.940839 kg | C04 fix plus splice pack charged |

## Drag and Power Summary

| Quantity | Value | Read |
|---|---:|---|
| Tail CD0 increment | 0.002352 | screening drag placeholder |
| Tail profile power increment | 13.33234 W | screening power charge |
| QPROP/XROTOR propulsion margin | not mixed | independent propulsion lane, not structural blocker truth |

## Missing Data Preventing Higher Confidence

- measured component weights and measured aircraft CG
- full y/z component locations for inertia and lateral/vertical balance
- supplier-quoted spar splice, tube, clamp, and saddle/yoke masses
- coupon/local FEM evidence for C04 saddle/yoke/clamp and C07 skin sag
- independent QPROP/XROTOR propulsion margin feed-in

## Trust Boundary

All current component masses are `estimate` confidence. Do not promote them to `quoted`, `measured`, or `frozen` until supplier, scale, or configuration-control evidence exists. The managed CG row is allowed for screening closure; the uncompensated CG row is rejected.
