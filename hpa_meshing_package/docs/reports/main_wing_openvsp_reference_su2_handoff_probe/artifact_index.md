# main_wing OpenVSP reference SU2 handoff artifact index

This directory is a probe-local OpenVSP/VSPAERO reference-policy snapshot for
the real main-wing mesh handoff. It does not replace the default
`main_wing_real_su2_handoff_probe` report.

- `main_wing_openvsp_reference_su2_handoff_probe.v1.json`: report copied from
  `.tmp/runs/main_wing_openvsp_reference_su2_handoff_probe`.
- `main_wing_openvsp_reference_su2_handoff_probe.v1.md`: markdown summary.
- `artifacts/su2_handoff.json`: small handoff contract snapshot showing
  `reference_mode=geometry_derived`.
- `artifacts/su2_runtime.cfg`: SU2 runtime config snapshot showing
  `V=6.5`, `REF_AREA=35.175`, `REF_LENGTH=1.0425`, and the `main_wing` force
  marker.

The full generated `mesh.su2` is intentionally not committed here because it is
a duplicate heavyweight mesh copy. The report keeps the original `.tmp` path
for the materialized case used during this probe run.
