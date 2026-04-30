# Main Wing Station-Seam Side-Aware PCurve Residual Diagnostic v1

`main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1` is a
report-only diagnostic for the side-aware station-seam candidate. It reads the
side-aware BRep validation report, resolves the candidate STEP, samples each
selected station edge against its PCurve-on-owner-face geometry, and separates
sampled geometric residual from ShapeAnalysis / SameParameter metadata flags.

The diagnostic must record:

- source side-aware BRep validation probe path
- candidate STEP path
- target station `y` values
- whether old fixture curve / surface tags were replayed
- sample count and residual tolerance policy
- edge-face sampled residuals, edge tolerances, vertex tolerances, curve /
  PCurve types, parameter ranges, and ShapeAnalysis flags
- residual summary, engineering findings, blockers, next actions, and
  limitations

Current status meanings:

- `side_aware_station_pcurve_residuals_sampled_clean`: sampled edge-face
  residuals are within tolerance and ShapeAnalysis flags do not fail. This is a
  diagnostic pass only; BRep validation and mesh handoff still govern route
  readiness.
- `side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail`:
  sampled 3D-vs-PCurve residuals are within edge tolerance, but ShapeAnalysis /
  SameParameter / vertex-tolerance flags still fail. This points to a
  metadata/parameterization repair gate, not a solver-iteration gate.
- `side_aware_station_pcurve_sampled_residuals_exceed_tolerance`: at least one
  sampled edge-face residual exceeds tolerance; geometry/PCurve repair is
  required before metadata repair.
- `side_aware_station_pcurve_residual_diagnostic_unavailable`: the OCP runtime
  or STEP sampling path was unavailable.
- `blocked`: required inputs are missing or invalid.

For the current main-wing route, the committed evidence is
`side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail`:
12 edge-face pairs were sampled on the side-aware candidate, the sampled
3D-vs-PCurve residual max is `0.0 m`, all PCurves are present, and old fixture
tags were not replayed. However, all 12 edge-face ShapeAnalysis flags still
fail, and all PCurves are unbounded `Geom2d_Line` domains. The route therefore
remains blocked before mesh handoff; the next gate is a bounded same-parameter /
metadata repair probe for the side-aware candidate, not a solver-budget run or
a convergence claim.
