# Main Wing Station-Seam Side-Aware Export Opcode Variant Probe v1

`main_wing_station_seam_side_aware_export_opcode_variant_probe.v1` is a
report-only upstream export diagnostic for the main-wing side-aware station-seam
route. It rebuilds report-local OpenCSM candidates from the side-aware
profile-parametrization audit and changes only the local opcode policy used in
candidate `.csm` files. It must not mutate provider defaults, production route
defaults, mesh sizing defaults, or SU2 settings.

The probe must record:

- profile-parametrization audit path
- source `rebuild.csm` path
- selected station `y` targets
- evaluated opcode variants
- materialization status for each variant
- topology counts for each materialized variant
- validation status or surface-count guard status
- variant summary
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `side_aware_export_opcode_variant_recovered`: at least one report-local opcode
  variant materialized and passed the side-aware station BRep/PCurve gate.
- `side_aware_export_opcode_variant_not_recovered`: variants materialized, but
  none recovered the side-aware station gate.
- `side_aware_export_opcode_variant_source_only_ready_for_materialization`:
  variant CSM sources can be generated, but materialization was not requested.
- `side_aware_export_opcode_variant_materialization_failed`: materialization was
  requested, but no variant produced usable STEP evidence.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`side_aware_export_opcode_variant_not_recovered`. The report-local
`upper_lower_spline_split` candidate materializes as `1 volume / 52 surfaces`
and reaches BRep validation, but its station PCurve metadata gate remains
suspect (`best_station_edge_check_count = 10`, `recovered_variant_count = 0`).
The `all_linseg` candidate materializes as `1 volume / 582 surfaces`, which is a
surface-count explosion and is stopped by the validation guard.

The engineering conclusion is negative but useful: simple OpenCSM opcode
changes are not enough to recover the station-seam PCurve metadata gate, and
`all_linseg` should be treated as a negative control rather than a product
candidate. The next repair should inspect export PCurve metadata generation
directly. This probe is not mesh handoff, SU2 handoff, solver execution,
convergence, or CL acceptance evidence.
