# Baseline A Carbon Tube RFQ + Procurement Screening Pack

Verdict: `carbon_tube_rfq_pack_draft_vendor_screening`

Draft vendor-screening pack only while mass/span authority is under repair; it is not purchase-ready, not supplier selection, not drawing release, and not final aircraft sign-off.

## RFQ Use

Keep this pack as a draft capability and quote-screening request until mass/span authority is repaired. If it is shared externally, every page must preserve the draft/vendor-screening boundary. Do not authorize production or procurement from this pack.

## Controlled Station Convention For RFQ

| Item | RFQ convention | Status |
|---|---|---|
| Half-wing station | Positive `y` from aircraft centerline/root, mirrored left/right | draft_vendor_screening |
| Local/splice screening extent | `16.500 m` half-span, not procurement truth | conflict_blocked |
| Transport panel length | `3.000 m` maximum shipped/cut panel | screening_constraint |
| Splice stations | `3 / 6 / 9 / 12 / 15 m` per half-wing | draft_vendor_screening |
| Release rib basis | `0.30 m` target; max materialized bay `0.297063 m` | controlled_for_rfq_language |
| Airfoil/control/twist/transport station contracts | Not final drawing control | open |

The draft station convention intentionally does not use the signed full-wing rib table as the vendor station origin. Materialized spar-joint ribs are reference hard-points until a drawing-controlled station schedule exists.

## Tube And Spar Assumptions

| Role | Basis | Full-wing quantity basis | Status |
|---|---:|---:|---|
| Main spar tube | 100.0 mm OD / 98.0 mm ID / 1.0 mm wall / 0.494 kg/m | 12 x <=3 m segments plus spare allowance open | screening_reference |
| Rear spar tube | 80.0 mm OD / 78.0 mm ID / 1.0 mm wall / 0.394 kg/m | 12 x <=3 m segments plus spare allowance open | screening_reference |
| Main-spar internal spigot | OD approx spar ID - 0.2 mm clearance; 4D overlap each side | 10 joints full-wing on current main-spar splice screen | screening_reference |
| Ferrule / shear dog | CFRP ferrule ring plus two shear dogs; removable pin never through CFRP spar | 10 joints full-wing on current main-spar splice screen | screening_reference |

Quantity basis is only a draft estimate tied to the local/splice screening half-span. The outer aero/rib tip extension is not yet a tube purchase length control, and the 16.5 m reference is not procurement truth.

## Splice Screening Table

| y [m] | M [N*m] | V [N] | T [N*m] | spigot wall [mm] | overlap [mm] | governing margin | governs | RFQ read |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| 3.0 | 4436.8 | 767.7 | 24.979 | 1.02 | 400.0 | 0.000 | spigot:bending | critical warning; vendor tolerance/ovality/knockdown can consume margin |
| 6.0 | 2477.1 | 545.9 | 22.914 | 0.80 | 400.0 | 0.420 | spigot:bending | screening pass; still needs vendor fit data |
| 9.0 | 1148.4 | 345.2 | 20.771 | 0.80 | 400.0 | 2.064 | spigot:bending | screening pass; still needs vendor fit data |
| 12.0 | 377.3 | 174.7 | 18.513 | 0.80 | 400.0 | 8.324 | spigot:bending | screening pass; still needs vendor fit data |
| 15.0 | 50.2 | 53.1 | 16.049 | 0.80 | 400.0 | 69.085 | spigot:bending | screening pass; still needs vendor fit data |

## Required WO-004 Carryover

| Warning | RFQ handling |
|---|---|
| `span_extent_contract_mismatch` | Structural half-span is 16.500 m, while aero/rib evidence extends to 17.166/17.324 m. Resolve this before RFQ. |
| `splice_station_contract_mismatch` | 3 m RFQ-style splice stations conflict with materialized spar-joint rib stations unless one manifest owns the convention. |
| `inboard_splice_zero_margin_rfq_warning` | The y=3 m splice only screens at zero bending margin. Treat as a vendor/detail warning, not a release reopen yet. |
| `release_vs_selected_stiffness_rib_spacing` | Release-facing 0.30 m station trace and later 0.345 m selected stiffness bookkeeping must be reconciled before procurement language. |
| `continuous_dimensions_not_shop_grid` | Continuous station values are acceptable for screening but need a 0.05/0.10 m or rib-bay shop grid before team release drawings. |
| `airfoil_control_transition_contracts_missing` | Airfoil, twist, control, and transport station contracts are still missing in the materialized rib audit. |

## P1 And C04 Boundary

- P1 verdict remains `p1_local_load_path_ready_for_coupon_fem`.
- C04 selected fix remains `saddle_ring_yoke_plus_secondary_clamp` with screening governing margin `0.8876`.
- C04 original eccentric peel fail remains visible: margin `-0.893`.
- Splice mass already carried in mass ledger: `3.847 kg` full-wing screening estimate.
- QPROP/XROTOR is independent and is not used to pass this RFQ or structural blocker.

## Procurement Review Triggers

- Vendor cannot quote or make the 100/98 main or 80/78 rear HM CFRP tube family with credible tolerance data.
- Vendor tolerance, ovality, straightness, laminate, or wall-thickness data invalidates sleeve/spigot fit.
- Vendor knockdowns or test data make the y=3 m splice negative after local detail review.
- Vendor changes OD/wall/layup enough to move mass/CG or spar stiffness assumptions.
- Vendor cannot support 3 m segment shipping, inspection, replacement, or certificate traceability.
- Vendor surface prep is incompatible with ferrules, saddle rings, spigots, or adhesive/coupon plans.

## Source Artifacts

- `output/baseline_A_team_release/geometry_freeze.json`
- `output/baseline_A_team_release/manufacturable_geometry_audit/geometry_discretization_report.csv`
- `output/baseline_A_team_release/manufacturable_geometry_audit/smoothness_warning.json`
- `output/current_pathfinder_materialized_rib_contract_audit/materialized_rib_contract_audit.json`
- `output/current_pathfinder_spar_splice_design/splice_design_report.json`
- `output/current_pathfinder_p1_load_path_mass_closure/p1_load_path_mass_closure.json`
- `data/carbon_tubes.csv`

## Engineering Verdict

`carbon_tube_rfq_pack_draft_vendor_screening`: retained for vendor capability questions only inside the stated trust boundary. It is not ready for purchase authorization or final drawing release.

Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
Selected rib/stiffness basis carried for release: `The 0.30 m bay is accepted only as this materialized station layout, not as a naked local-wall-buckling assumption.`
