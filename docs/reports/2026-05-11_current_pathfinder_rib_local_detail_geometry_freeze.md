# Current Pathfinder Rib / Local Detail Geometry and Allowable Freeze Sheet

> Date: 2026-05-11
> Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
> Station: R068 at y = 2.327955 m
> Schema: `rib_local_detail_geometry_freeze_v1`

## Purpose

This is Step 1 of the FEM/Coupon Plan from the 2026-05-10 local-validation shortlist.
It fills all eight open items in the missing-data register with engineering estimates,
derives spar-tube dimensions from the config thickness-fraction parameters, and computes
preliminary margins for the seven local failure modes.

Parameters tagged **engineering_estimate** must be replaced with supplier data or
coupon results before the local FEM/APDL run is considered a qualified margin claim.

## Station Summary

| item | value |
|---|---:|
| station | R068 |
| y | 2.327955 m |
| chord | 1.184552 m |
| spar separation | 0.533385 m |
| kernel torque | -12.715548 N·m |
| torque couple | 23.839355 N |
| load factor | 2.0 |
| design couple force (factored) | 47.6787 N |

## Spar Tube Geometry (Design Derived)

OD is derived as: `chord × t/c(y) × thickness_fraction_root` then rounded DOWN to the
nearest catalog tube. This is the MAXIMUM allowable OD; the structural optimizer may
select a smaller tube based on bending and buckling requirements.

| item | main spar | rear spar |
|---|---:|---:|
| catalog product | CF-HM-100x98 | CF-HM-80x78 |
| OD | 100 mm | 80 mm |
| wall | 1.0 mm | 1.0 mm |
| confidence | design_derived | design_derived |

**Note:** Derived max OD; optimizer may select smaller. Awaiting optimizer confirmation.

## Missing Data Register — Filled Values

| data key | filled value | confidence | source |
|---|---|---|---|
| main_spar_od_m | 0.1 | design_derived | config thickness_fraction_root x t/c x chord; near |
| main_spar_wall_m | 0.001 | design_derived | catalog |
| rear_spar_od_m | 0.08 | design_derived | config t/c + thickness_fraction |
| rear_spar_wall_m | 0.001 | design_derived | catalog |
| collar_material (P1) | cfrp_ply_sm | design_intent | shortlist report |
| collar_thickness_m | 0.0005 | design_intent | 4-ply CF estimate |
| collar_contact_width_m | 0.085 | design_intent | shortlist report |
| bondline_width_m | 0.015 | engineering_estimate | typical HPA lap joint |
| bondline_thickness_m | 0.0003 | engineering_estimate | thin bond |
| adhesive_shear_allowable_pa | 2e+07 | engineering_estimate | Araldite 420 class |
| adhesive_peel_allowable_n_per_m | 400 | engineering_estimate | structural epoxy |
| balsa_cap_shear_allowable_pa | 6e+06 | engineering_estimate | G×3% strain limit |
| eps_core_shear_allowable_pa | 1e+05 | engineering_estimate | shape support only |
| skin_thickness_m | 3e-05 | engineering_estimate | 25 μm Mylar standard |

## Preliminary Margins (7 Failure Modes)

> These are PRELIMINARY estimates. Model simplifications: half-circumference bond area,
> peel fraction = 0.20, thin-shell hoop stress, membrane skin sag. Replace with full
> local FEM and coupon data for qualified margins.

| coupon | failure mode | stress / load | allowable | margin | status |
|---|---|---:|---:|---:|---|
| C01 | cap shear transfer | 46182 Pa | 6e+06 Pa | 128.9 | pass |
| C02 | main spar bond shear | 3571 Pa | 2e+07 Pa | 5039.7 | pass |
| C03 | rear spar bond shear | 4464 Pa | 2e+07 Pa | 4031.5 | pass |
| C04 | bond peel (main) | 9.536 N | 34.000 N | 2.6 | pass |
| C05 | collar bearing | 1121852 Pa | 4e+08 Pa | 355.6 | pass |
| C06-M | tube crush (main) | 280463 Pa | 4e+08 Pa | 1336.1 | pass |
| C06-R | tube crush (rear) | 280463 Pa | 4e+08 Pa | 1336.1 | pass |
| C07 | skin sag | 0.487 %c | 0.50 %c | 0.03 | pass |

Preliminary worst margin: **0.03** (C07 skin sag).

**Important:** All margins appear comfortable at screening load levels. This is
expected for HPA structures. The purpose of the local FEM is NOT to find near-zero
margins but to confirm that the simplified preliminary model is not hiding stress
concentrations, peel failures, or ovalization under point loads.

## Skin Sag Process Warning

Sag is computed at pre-strain = 0.05%. Computed sag: **5.8 mm** = **0.487% chord**.

> PROCESS-SENSITIVE: sag scales with 1/pre_strain. 0.05% pre-strain assumed; lower values cause >1% chord sag.

## Next Actions

| step | action | unblocked by this sheet |
|---|---|---|
| Step 2 | P1 local FEM pre-margin run at y=2.328 m | Yes — fill APDL skeleton with frozen values |
| Step 3 | P1 coupon matrix C01–C07 | Yes — geometry and failure modes pinned |
| Step 4 | P1 local margin report | Requires Step 2 + Step 3 |
| Step 5 | P2 reserve comparison (12 mm) | After P1 FEM baseline |
| Step 6 | P3 manufacturability fallback (glass collar) | After P1 |
| Step 7 | Ordinary bay validation | After torque-zone results |

## Supplier Confirmation Priority

Replace the following engineering estimates BEFORE Step 4 margin report:

1. **Adhesive**: supplier datasheet for actual adhesive system — shear strength, peel
   strength, bondline thickness, cure schedule.
2. **Spar tube OD/wall**: structural optimizer output at y=2.328 m to confirm whether
   the max-OD assumption holds or the optimizer selected a smaller tube.
3. **Balsa cap shear allowable**: diagonal shear coupon on EPS+balsa cap specimen
   matched to actual grain direction and cap strip dimensions.
4. **Collar bearing**: bearing coupon on CF collar on representative spar tube section.
5. **Skin pre-strain**: covering process specification confirming target pre-strain and
   inspection method.

## Claim Boundary

> Geometry freeze and preliminary margins for P1 y=2.328 m local detail validation. Parameters tagged 'engineering_estimate' must be replaced with supplier or coupon data before qualified margin claims. This is not final bond, collar, tube-wall, buckling, or aircraft sign-off.