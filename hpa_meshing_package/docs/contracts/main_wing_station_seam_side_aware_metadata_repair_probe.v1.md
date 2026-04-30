# Main Wing Station-Seam Side-Aware Metadata Repair Probe v1

`main_wing_station_seam_side_aware_metadata_repair_probe.v1` is a report-only
bounded repair feasibility gate for the side-aware station-seam candidate. It
consumes the side-aware BRep validation report and the side-aware PCurve
residual diagnostic, resolves the candidate STEP, and runs bounded in-memory
OCCT metadata repair attempts using `BRepLib.SameParameter` and
`ShapeFix_Edge`.

The probe must record:

- side-aware BRep validation report path
- side-aware PCurve residual diagnostic path
- candidate STEP path
- candidate-selected station edge ids and owner face ids
- evaluated tolerances and ShapeFix operations
- residual context summary from the PCurve residual diagnostic
- SameParameter baseline checks, per-attempt checks, and attempt summary
- ShapeFix baseline checks, per-attempt checks, and attempt summary
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `side_aware_station_metadata_repair_recovered`: at least one bounded
  SameParameter or ShapeFix attempt made every target station-edge PCurve,
  same-parameter, curve-3D-with-PCurve, and vertex-tolerance check pass.
- `side_aware_station_metadata_repair_not_recovered`: attempts ran, but no
  operation/tolerance combination recovered the side-aware station metadata
  gate.
- `side_aware_station_metadata_repair_unavailable`: the OCP runtime or repair
  helper execution was unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`side_aware_station_metadata_repair_not_recovered`. The side-aware candidate has
six target station edges and 12 owner-face pairs; the preceding residual
diagnostic observed `max_sample_distance_m = 0.0`, but all 12 ShapeAnalysis /
same-parameter / vertex-tolerance flags still fail. A bounded
`BRepLib.SameParameter` sweep over five tolerances and a 25-attempt
`ShapeFix_Edge` operation/tolerance sweep both have
`recovered_attempt_count = 0`.

The engineering conclusion is that the current side-aware candidate needs an
explicit PCurve/export metadata construction path before mesh handoff. This is
not a Gmsh pass, SU2 pass, solver convergence result, or CL acceptance result.
