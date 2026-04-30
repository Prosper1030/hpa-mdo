# Main Wing Surface Force Output Audit v1

`main_wing_surface_force_output_audit.v1` is a report-only gate for the real
main-wing solver-smoke route. It reads existing solver reports, raw solver logs,
and VSPAERO panel-reference reports; it does not execute SU2 and does not change
production defaults.

The audit must record:

- selected main-wing solver-smoke report path
- selected solver log path
- selected VSPAERO panel-reference report path
- solver execution status, final iteration, coefficients, and HPA flow speed
- expected surface-force outputs parsed from the solver log
- retained or pruned `surface.csv` / `forces_breakdown.dat` artifacts
- panel-reference CL and selected SU2 smoke CL when available
- engineering flags and blockers

Required checks:

1. `solver_report_available` passes when the selected solver-smoke report can be
   loaded.
2. `solver_executed` passes when the report records `solver_execution_status =
   solver_executed`. This is not a convergence claim.
3. `surface_csv_retained` passes only when the expected `surface.csv` exists in
   a committed raw-solver artifact location or in the still-existing runtime case
   directory.
4. `forces_breakdown_retained` passes only when the expected
   `forces_breakdown.dat` exists in a committed raw-solver artifact location or
   in the still-existing runtime case directory.
5. `panel_force_comparison_ready` passes only when a panel reference is available
   and both surface-force outputs are retained.

If the solver log expects `surface.csv` / `forces_breakdown.dat` but the route
snapshot does not retain them, the audit must be `blocked` with
`surface_force_output_pruned_or_missing`, `forces_breakdown_output_missing`, and
`panel_force_comparison_not_ready` as applicable.

At the HPA standard `V=6.5 m/s`, the audit may derive
`main_wing_lift_acceptance_status=fail` when the selected solver-smoke CL is not
greater than `1.0`. This derived label is an engineering acceptance gate; it must
not be reported as a convergence result.
