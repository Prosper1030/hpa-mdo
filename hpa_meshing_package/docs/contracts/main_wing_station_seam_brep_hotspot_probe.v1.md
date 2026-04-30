# Main Wing Station-Seam BRep Hotspot Probe v1

`main_wing_station_seam_brep_hotspot_probe.v1` is a report-only diagnostic gate
for the real main-wing route. It reads existing main-wing geometry / topology
artifacts and inspects the BRep representation of station-seam hotspot curves.
It does not run Gmsh, does not run SU2, and does not change production
defaults.

The probe must record:

- source station-topology fixture path
- source real mesh-handoff probe path
- selected normalized STEP path
- optional surface-patch diagnostics path
- requested curve and surface tags
- observed station-fixture summary
- BRep hotspot summary, including shape validity and unit scale
- per-curve checks for length mapping, owner faces, PCurve presence,
  curve-3D-with-PCurve consistency, same-parameter status, vertex tolerance, and
  PCurve range agreement
- per-face checks for wire order, connectivity, closedness, and
  self-intersection status
- prototype candidates, engineering findings, blockers, next actions, and
  limitations

Current status meanings:

- `brep_hotspot_captured_station_edges_valid`: all requested station-seam BRep
  checks are captured and no suspect consistency checks remain.
- `brep_hotspot_captured_station_edges_suspect`: requested station-seam edges
  are captured, but at least one geometry-consistency check remains suspect.
- `unavailable`: required runtime support for the diagnostic is unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`brep_hotspot_captured_station_edges_suspect`. Curves 36 and 50 map to the
expected STEP edges after `scale_to_output_units=0.001`, and owner faces
12 / 13 / 19 / 20 have closed, connected, ordered wires. PCurves are present,
but curve-3D-with-PCurve, same-parameter-by-face, and
vertex-tolerance-by-face checks remain suspect.

This report may propose prototype meshing or repair candidates, but those
candidates are not production behavior unless a later gate materializes and
tests them explicitly.
