# Main Wing Station-Seam Side-Aware Projected PCurve Builder Probe v1

`main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1` is a
report-only feasibility gate for rebuilding side-aware station-edge PCurves
from the 3D edge and owner surface. It consumes the side-aware PCurve metadata
builder report, resolves the same candidate STEP, and tests projected or sampled
in-memory OCCT/OCP PCurve construction strategies.

The probe must record:

- side-aware PCurve metadata builder report path
- candidate STEP path
- candidate-selected station edge ids and owner face ids
- evaluated projected / sampled PCurve strategies
- upstream bounded-PCurve builder summary
- baseline edge-face metadata checks
- per-strategy operation results, endpoint-orientation gates, and checks
- strategy attempt summary
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `side_aware_station_projected_pcurve_builder_recovered`: at least one
  strategy made every target edge-face pair pass projected-PCurve construction,
  endpoint orientation, bounded-domain, PCurve-range, same-parameter,
  curve-3D-with-PCurve, and vertex-tolerance checks.
- `side_aware_station_projected_pcurve_builder_partial`: at least one strategy
  built projected or sampled PCurves and/or passed endpoint orientation, but no
  strategy recovered the full station metadata gate.
- `side_aware_station_projected_pcurve_builder_not_recovered`: strategies ran
  without recovery or meaningful partial progress.
- `side_aware_station_projected_pcurve_builder_unavailable`: the OCP runtime or
  projected-PCurve helper execution was unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`side_aware_station_projected_pcurve_builder_partial`. Three in-memory
strategies were tested: `GeomProjLib.Curve2d`, sampled
`GeomAPI_ProjectPointOnSurf + Geom2dAPI_Interpolate`, and sampled
`GeomAPI_ProjectPointOnSurf + Geom2dAPI_PointsToBSpline`. Across 36
strategy/edge-face operations, all projected PCurves were built and all endpoint
orientation gates passed. The sampled strategies reached
`max_projection_distance_m = 1.8343894894033213e-15`.

The engineering conclusion is negative but useful: the gross edge/surface
geometry and endpoint ordering are not the limiting issue, because projection
and orientation evidence are clean. However, 0 / 12 target edge-face pairs pass
the full ShapeAnalysis metadata gate after the projected / sampled PCurve
strategies, and SameParameter / SameRange flags can be true while the gate still
fails. The next repair should move upstream to section parametrization or export
PCurve metadata generation. This is not a Gmsh pass, SU2 pass, solver
convergence result, or CL acceptance result.
