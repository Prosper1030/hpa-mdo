# Main Wing SU2 Force Marker Audit v1

`main_wing_su2_force_marker_audit.v1` is a report-only gate for the real
main-wing SU2 handoff route. It reads existing SU2 handoff, runtime config, and
mesh marker artifacts; it does not execute SU2 and does not change production
defaults.

The audit must record:

- source SU2 probe report path
- selected `su2_handoff.json` path
- selected `su2_runtime.cfg` path
- source mesh marker summary path
- force-surface provenance
- SU2 runtime marker declarations
- mesh marker element counts
- flow and reference quantities observed in handoff/config
- engineering flags and blockers

Required checks:

1. `force_surface_provenance` passes when the force surface provenance gate is
   `pass`, the force surface matches the wall marker, and the primary group has
   positive surface elements.
2. `runtime_cfg_markers` passes when `MARKER_EULER`, `MARKER_MONITORING`, and
   `MARKER_PLOTTING` include the main-wing wall marker and `MARKER_FAR` includes
   the farfield marker.
3. `mesh_marker_counts` passes when both `main_wing` and `farfield` mesh marker
   groups exist and have positive element counts.
4. `flow_reference_consistency` passes when `V=6.5 m/s` is preserved and
   `REF_AREA` / `REF_LENGTH` match the handoff reference geometry.

`audit_status=warn` is allowed for report-scope warnings such as Euler-wall
smoke scope or reference moment-origin warnings. This must not be reported as
CFD-ready or as a converged aerodynamic result.
