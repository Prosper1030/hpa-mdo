# Main Wing Station Seam Internal Cap Probe v1

- status: `split_candidate_internal_cap_risk_confirmed`
- production_default_changed: `False`
- export_strategy_probe_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_export_strategy_probe/main_wing_station_seam_export_strategy_probe.v1.json`
- station_plane_tolerance: `0.0001`
- target_station_y_m: `[-10.5, 13.5]`

## Candidate Inspections

| candidate | mesh ready | bodies | volumes | span preserved | target face counts |
| --- | ---: | ---: | ---: | ---: | --- |
| `split_at_defect_sections_no_union` | `False` | `3` | `3` | `True` | `-10.5:2, 13.5:2` |
| `split_at_defect_sections_union` | `False` | `1` | `1` | `False` | `-10.5:0, 13.5:6` |

## Engineering Findings

- `station_seam_internal_cap_probe_captured`
- `split_at_defect_sections_no_union_duplicate_station_cap_faces_confirmed`
- `split_at_defect_sections_no_union_multi_volume_topology_reconfirmed`
- `split_at_defect_sections_union_duplicate_station_cap_faces_confirmed`
- `split_at_defect_sections_union_span_truncation_reconfirmed`

## Blocking Reasons

- `internal_station_cap_faces_present`
- `duplicate_station_cap_faces_present`
- `split_candidate_span_truncation_confirmed`
- `split_candidate_multi_volume_topology_confirmed`
- `split_candidate_not_mesh_handoff_ready`

## Next Actions

- `try_pcurve_rebuild_strategy_without_split_caps`
- `keep_split_bay_strategy_as_negative_evidence_not_product_route`

## Limitations

- This report classifies station-plane cap faces from OCC/Gmsh surface bounding boxes; it does not mesh or run SU2.
- A clean result here would only authorize a bounded mesh-handoff probe, not production-route promotion.
