# Main Wing Station-Seam Internal Cap Probe v1

`main_wing_station_seam_internal_cap_probe.v1` is a report-only topology
inspection gate for split-at-defect-section main-wing export candidates. It
consumes the station-seam export-strategy report and its source export audit,
then imports materialized candidate STEP files through OCC/Gmsh to classify
station-plane faces at the target defect stations. It does not mesh, write SU2,
run a solver, change `esp_rebuilt`, or promote a production default.

The probe must record:

- source export-strategy report path
- source export-audit path when available
- station-plane tolerance
- target defect station `y` values
- candidate materialization status and STEP path
- OCC/Gmsh body, volume, surface, and bounding-box evidence
- per-target-station plane-face counts, tags, bounding boxes, and duplicate
  cap-face classification
- candidate mesh-handoff readiness, engineering findings, blockers, next
  actions, and limitations

Current status meanings:

- `split_candidate_no_internal_caps_detected_needs_mesh_handoff_probe`: at
  least one candidate is materialized, imports as one body / one volume,
  preserves full span bounds, and has no station-plane cap faces at the target
  defect stations. This only authorizes a bounded mesh-handoff probe; it is not
  production-route promotion.
- `split_candidate_internal_cap_risk_confirmed`: no candidate is ready for mesh
  handoff because cap faces, multi-volume topology, span truncation, or missing
  surface inventory remains.
- `blocked`: required source reports or target station values are missing.

For the current main-wing route, the committed evidence is
`split_candidate_internal_cap_risk_confirmed`. The no-union split candidate has
duplicate station cap faces at both `y=-10.5 m` and `y=13.5 m` and imports as
three volumes. The union candidate imports as one volume, but truncates the
right span to `y=13.5 m` and leaves six station-plane cap fragments at that
station.

This is negative evidence for promoting the split-bay export strategy. The next
gate should try a PCurve/export rebuild strategy that avoids duplicate station
caps before any mesh handoff or solver-budget campaign.
