# Main Wing Station-Seam Side-Aware PCurve Metadata Builder Probe v1

`main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1` is a
report-only feasibility gate for explicit side-aware station-edge PCurve
metadata construction. It consumes the side-aware BRep validation report and
the side-aware metadata repair probe, resolves the candidate STEP, and tests
bounded in-memory OCCT/OCP PCurve construction strategies.

The probe must record:

- side-aware BRep validation report path
- side-aware metadata repair probe path
- candidate STEP path
- candidate-selected station edge ids and owner face ids
- evaluated PCurve metadata builder strategies
- upstream SameParameter / ShapeFix repair summary
- baseline edge-face metadata checks
- per-strategy operation results and checks
- strategy attempt summary
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `side_aware_station_pcurve_metadata_builder_recovered`: at least one strategy
  made every target edge-face pair pass PCurve presence, bounded-domain,
  PCurve-range, same-parameter, curve-3D-with-PCurve, and vertex-tolerance
  checks.
- `side_aware_station_pcurve_metadata_builder_partial`: at least one strategy
  improved the metadata evidence, such as bounding every existing PCurve
  domain, but no strategy recovered the full station metadata gate.
- `side_aware_station_pcurve_metadata_builder_not_recovered`: strategies ran
  without recovery or meaningful partial progress.
- `side_aware_station_pcurve_metadata_builder_unavailable`: the OCP runtime or
  builder helper execution was unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`side_aware_station_pcurve_metadata_builder_partial`. The existing side-aware
station PCurves are present and sample at `max_sample_distance_m = 0.0`, but
baseline PCurve domains are unbounded `Geom2d_Line` objects and 0 / 12 target
edge-face pairs pass the full metadata gate. Four in-memory bounded-existing
PCurve strategies make 12 / 12 PCurve domains bounded, but still leave 0 / 12
edge-face pairs passing same-parameter, curve-3D-with-PCurve, and
vertex-tolerance checks.

The engineering conclusion is that bounded-domain wrapping alone is not enough.
The next route gate is a projected or sampled PCurve builder with explicit
vertex-parameter and orientation validation. This is not a Gmsh pass, SU2 pass,
solver convergence result, or CL acceptance result.
