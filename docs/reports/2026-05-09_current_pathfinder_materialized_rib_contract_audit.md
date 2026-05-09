# Current Pathfinder Materialized Rib Contract Audit

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `blocked_needs_materialized_bond_shape_data`
Local FEM verdict: `local_fem_required_before_hybrid_pass_claim`

## Materialized Trace

- rib family: `balsa_sheet_3mm`; target spacing `0.300` m
- full-wing ribs/stations: `121`; bays: `120`
- max materialized bay: `0.297063` m
- full-wing rib mass basis: `3.029671` kg
- rear spar participation: `bounded_50pct_screening`; warping knockdown `0.502460`

The 0.30 m bay is materialized in the station/bay tables. That does not close skin sag, bond, collar, spar contact, or local FEM margins.

## Mandatory Contract

| item | status | y m | ribs |
|---|---|---|---|
| root | `materialized_mandatory` | 0.000000 | R060 |
| tip | `materialized_mandatory` | -17.324041;17.324041 | R000;R120 |
| wire_attach | `materialized_mandatory` | -7.573654;-7.564741;7.564741;7.573654 | R033;R034;R086;R087 |
| spar_joint | `materialized_mandatory` | -13.462227;-10.509126;-7.573654;-4.365292;-1.454811;1.454811;4.365292;7.573654;10.509126;13.462227 | R013;R023;R033;R045;R055;R065;R075;R087;R097;R107 |
| transport_joint | `missing_contract` | n/a | n/a |
| control_station | `missing_contract` | n/a | n/a |
| airfoil_transition | `missing_contract` | n/a | n/a |
| twist_transition | `missing_contract` | n/a | n/a |

Missing contract rows are intentional blockers, not assumed pass states.

## Torque-Critical Zone

- peak twist station y: `2.327757` m
- direct / bounded twist: `5.413494` deg / `3.256324` deg
- screening bound: `3.000` deg
- dominant source: `aerodynamic_torque_only`
- local FEM station count: `21`; local FEM bay count: `34`

Recommended hybrid reinforcement zones:

- `positive_torque_critical_hybrid_reinforcement_zone`: y `2.028` to `2.628` m; stations `R067;R068;R069`
- `negative_torque_critical_hybrid_reinforcement_zone`: y `-2.628` to `-2.028` m; stations `R051;R052;R053`

## Shape / Bond Boundary

- Skin sag is `unknown_requires_test` or `unknown_requires_test_torque_zone`; no bay is marked pass.
- Bond/collar/spar contact is `needs_data`; torque or mandatory stations are elevated risk.
- EPS/XPS foam-only rows remain shape-core/riblet/skin-support references, not structural bracing pass rows.
- Hybrid rib rows are next rerun candidates only; this audit does not claim closure pass.

## Artifacts

- `rib_station_table_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/rib_station_table.csv`
- `rib_bay_table_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/rib_bay_table.csv`
- `mandatory_rib_reason_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/mandatory_rib_reason.csv`
- `rib_type_by_station_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/rib_type_by_station.csv`
- `skin_sag_screening_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/skin_sag_screening.csv`
- `bond_collar_risk_screening_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/bond_collar_risk_screening.csv`
- `local_fem_trigger_report_json`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/local_fem_trigger_report.json`
- `audit_json`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_materialized_rib_contract_audit/materialized_rib_contract_audit.json`
- `report_md`: `/Volumes/Samsung SSD/hpa-mdo/docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md`

## Engineering Read

The 0.30 m bay is materialized by physical ribs/stations, but the next hybrid stiffness sweep remains blocked by unknown skin sag, bond/collar/spar-contact detail, and local FEM evidence near the torque-critical station.

The next hybrid stiffness sweep should use the torque-critical stations/bays above, plus mandatory root/tip/wire/spar-joint detail zones. Any result that still lacks skin sag evidence, bond/collar/tube-wall allowables, or local FEM should remain blocked or needs-data.

Missing contract items: transport_joint, control_station, airfoil_transition, twist_transition.
