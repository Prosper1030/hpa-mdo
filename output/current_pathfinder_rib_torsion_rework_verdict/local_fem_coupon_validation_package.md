# Current Pathfinder Local FEM / Coupon Validation Package

Verdict: `ready_to_start_local_FEM_and_coupon_definition_not_FEM_APDL_package`
FEM/APDL package ready: `False`

## Closure Evidence

- Selected basis: `eps_balsa_cap_hybrid_10mm` / `bounded_65pct_screening`.
- Bounded twist status: `clears_bound`; bounded twist `2.070316` deg.
- Direct stress-test status: `above_bound_conservative_stress_test`; direct twist `3.449294` deg.
- Hybrid stiffness model owned by closure: `True` at scale `2.032971`.

## Local FEM Zones

- `positive_torque_critical_hybrid_reinforcement_zone`: y `2.028` to `2.628` m; stations `['R067', 'R068', 'R069']`; bays `['B066', 'B067', 'B068', 'B069']`.
- `negative_torque_critical_hybrid_reinforcement_zone`: y `-2.628` to `-2.028` m; stations `['R051', 'R052', 'R053']`; bays `['B050', 'B051', 'B052', 'B053']`.

## Workstreams

### rib_spar_bond_collar_local_fem

Positive and negative torque-critical hybrid zones around y≈2.328 m, including rib-to-main/rear-spar bondline, collar/gusset geometry, tube-wall bearing/crush, and peel/shear load transfer.

Inputs needed:
- cap/face/collar dimensions and material allowables
- bondline width, adhesive system, cure/process notes
- main/rear spar OD, wall, local contact footprint, and collar fit
- closure load-owner spanload/twist artifacts listed in this package

Exit condition: Local FEM or hand/FEM hybrid margins are positive for bond shear/peel, collar bearing, tube-wall crush, and rib cap/shear path.

### hybrid_rib_coupon_matrix

Coupons for EPS+balsa/cap hybrid rib shear transfer; EPS core is not credited as structural bracing by itself.

Inputs needed:
- cap strip material and grain/fiber direction
- rib web/core thickness and adhesive interface
- coupon shear, compression, peel, and repeatability data

Exit condition: Coupon allowables support the effective-GJ surrogate or force a lower stiffness scale before FEM/APDL packaging.

### skin_sag_panel_coupon

0.30 m bay shape-keeping and skin sag check for the materialized 121-station / 120-bay rib layout.

Inputs needed:
- skin material/thickness and attachment method
- representative pressure/handling load or conservative panel load
- allowable sag/twist tolerance tied to airfoil shape quality

Exit condition: Sag/shape coupon or panel analysis clears the bay tolerance without relying on foam-only structural bracing.

### transition_control_station_manifest

Transport joint, control station, airfoil transition, and twist transition station manifest.

Inputs needed:
- station IDs and y locations
- local rib type changes and reinforcement details
- control/transition hardware interfaces

Exit condition: Missing transition/control station contract blockers are closed before FEM/APDL package export.

### direct_stress_test_aero_surface_mapping

Map the conservative main/rear direct stress-test twist to a qualified aero-surface or elastic-axis twist observable.

Inputs needed:
- direct stress-test max station from closure rerun
- rib/shell/skin local geometry for aero-surface interpolation
- comparison against bounded physical projection and FEM shell mapping

Exit condition: Either the direct 3+ deg stress-test is shown conservative for the aero surface, or the stiffness model is downgraded and rerun.

## Do Not Promote

- rear_spar_participation_1p00_as_selected_basis
- EPS/XPS/structural-foam-only as structural bracing
- GJ scaling projection as FEM-ready evidence

## Next Task

Define the rib-spar bond/collar local FEM input deck and coupon matrix for the positive y≈2.328 m torque-critical zone first; mirror the negative zone after the geometry assumptions are stable.

## Claim Boundary

This package starts local FEM/coupon definition. It is not FEM/APDL package readiness and not flight hardware signoff.
