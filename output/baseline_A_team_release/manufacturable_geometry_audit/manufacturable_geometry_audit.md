# Baseline A Manufacturable Geometry Audit

Work order: `WO-004 Manufacturable Smoothness / Discretization Audit`
Verdict: `geometry_freeze_needs_fix`

Baseline A smooth geometry is good enough to keep as a team-release pathfinder, but not clean enough to hand to the shop or tube vendors as controlled dimensions yet. The audit found no large external-shape discontinuity that forces redesign; the blockers are station-control, span-extent, rib-spacing-language, and splice/RFQ margin issues.

This is not final manufacturing drawing sign-off.

## Key Numbers

- Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
- Aero span: `34.332286 m` (half `17.166143 m`)
- Production section tip y: `17.166143 m`
- Materialized rib extent: `17.324041 m`
- Structural splice half-span basis: `16.500000 m`
- Rib trace: `121` full-wing stations, max bay `0.297063 m`
- Inboard splice screen: y=`3.0 m`, margin `0.000`

## Findings

| Finding | Category | Release action |
|---|---|---|
| `main_wing_chord_smoothness` | `smooth_and_manufacturable` | Keep smooth basis; produce a controlled shop station table before drawings. |
| `twist_dihedral_loaded_shape_smoothness` | `smooth_and_manufacturable` | Keep as screening smooth geometry; do not call it aero-surface sign-off. |
| `continuous_dimensions_need_shop_grid` | `smooth_but_not_manufacturable` | Create a 0.05 or 0.10 m controlled station schedule tied to rib bays before RFQ/drawings. |
| `airfoil_section_handoff_contract` | `smooth_but_not_manufacturable` | Add airfoil-transition station contract to the WO-005/RFQ station manifest. |
| `rib_0p30_materialized` | `smooth_and_manufacturable` | Keep 0.30 m as release-facing bay trace, with local FEM/coupon caveats. |
| `release_vs_selected_stiffness_rib_spacing` | `smooth_but_not_manufacturable` | Before procurement, reconcile whether Baseline A controls 0.30 m physical ribs or the relaxed stiffness row. |
| `splice_station_contract_mismatch` | `manufacturable_but_geometry_discontinuity_risk` | Create one controlled transport/splice/station manifest before carbon tube RFQ. |
| `span_extent_contract_mismatch` | `manufacturable_but_geometry_discontinuity_risk` | Define whether the outer 0.67-0.82 m per side is aerodynamic tip structure, removable tip, or excluded from spar procurement. |
| `inboard_splice_zero_margin_rfq_warning` | `manufacturable_but_geometry_discontinuity_risk` | Carry as WO-005 RFQ warning; ask vendors for tube/spigot tolerance, sleeve fit, and local test evidence. |
| `control_tail_transition_station_contracts` | `smooth_but_not_manufacturable` | Add a station-interface manifest as a prerequisite note for WO-005/WO-009/WO-010. |
| `skin_sag_bond_collar_trust_boundary` | `smooth_but_not_manufacturable` | Keep one-meter wing-bay v2 and C04 coupon/local FEM ahead of build sign-off. |

## Core Engineering Answers

1. Main-wing chord, twist, dihedral, and loaded shape are smooth enough for screening release inspection; they are not CAD curvature or final aero-surface sign-off.
2. Continuous dimensions need a 0.05/0.10 m, rib-bay, or controlled segment grid before shop-facing use.
3. The 0.30 m rib basis is materialized in the station table, but the release package must reconcile that with the later 0.345 m relaxed stiffness bookkeeping.
4. 3 m transport splice stations and materialized spar-joint ribs are not the same station contract; one manifest must own this before RFQ.
5. The 16.5 m structural half-span and 17.17-17.32 m aero/rib extents are a hidden mismatch and need station-control cleanup.
6. The near-zero inboard splice bending margin is an RFQ/manufacturing warning, not a Baseline A reopen by itself.
7. No discontinuity was found that currently forces large external-shape, spar-spec, mass/CG, procurement, or Baseline A reopen.

## Warnings

- `span_extent_contract_mismatch`: Structural half-span is 16.500 m, while aero/rib evidence extends to 17.166/17.324 m. Resolve this before RFQ.
- `splice_station_contract_mismatch`: 3 m RFQ-style splice stations conflict with materialized spar-joint rib stations unless one manifest owns the convention.
- `inboard_splice_zero_margin_rfq_warning`: The y=3 m splice only screens at zero bending margin. Treat as a vendor/detail warning, not a release reopen yet.
- `release_vs_selected_stiffness_rib_spacing`: Release-facing 0.30 m station trace and later 0.345 m selected stiffness bookkeeping must be reconciled before procurement language.
- `continuous_dimensions_not_shop_grid`: Continuous station values are acceptable for screening but need a 0.05/0.10 m or rib-bay shop grid before team release drawings.
- `airfoil_control_transition_contracts_missing`: Airfoil, twist, control, and transport station contracts are still missing in the materialized rib audit.

## Checked Sources

- `output/baseline_A_team_release/geometry_freeze.json`
- `output/go_mode_main_wing_candidate/final_candidate_package/geometry_exports/production_inspection/current_avl_compromise_conservative_closed/geometry_manifest.json`
- `output/go_mode_main_wing_candidate/final_candidate_package/geometry_exports/production_inspection/current_avl_compromise_conservative_closed/section_table.csv`
- `output/phase9_structure_jig_smooth_planform/production_geometry_quality.csv`
- `output/current_pathfinder_materialized_rib_contract_audit/materialized_rib_contract_audit.json`
- `output/current_pathfinder_materialized_rib_contract_audit/mandatory_rib_reason.csv`
- `output/current_pathfinder_spar_splice_design/splice_design_report.json`
- `output/current_pathfinder_spar_splice_design/splice_joints.csv`
- `docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.json`
- `output/baseline_A_team_release/design_space_freeze_audit/baseline_A_reopen_risk.json`

## Trust Boundary

The audit supports Baseline A as a team release package with required station-manifest fixes. It does not approve production drawings, tube orders, final rib construction, adhesive/collar margins, aero-surface mapping, or aircraft sign-off.

## Next Recommended Work Order

`WO-005 Carbon Tube RFQ + Procurement Pack` after a controlled station/span/splice manifest is attached to the RFQ package.
