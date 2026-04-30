# Main Wing Solver Validation Policy v1

This policy report does not execute SU2 and does not change production defaults.

- policy_status: `source_backed_convergence_policy_recorded`
- hpa_standard_velocity_mps: `6.5`
- current_max_observed_iterations: `80`

## Meaning Boundary

The current 12/40/80-iteration main-wing solver artifacts may be used as route
smoke, history-parser smoke, and `run_only` diagnostic evidence. They must not
be used as engineering convergence validation or final CFD-ready evidence.

## Source-Backed Observations

- SU2 Solver Setup defines steady-state runs by `ITER` or convergence criteria,
  and separates residual and coefficient Cauchy stopping modes.
- The SU2 incompressible hydrofoil tutorial config uses `ITER=9999`,
  `CONV_FIELD=RMS_PRESSURE`, `CONV_RESIDUAL_MINVAL=-15`,
  `CONV_STARTITER=10`, and `CONV_CAUCHY_ELEMS=50`.
- The SU2 inviscid ONERA M6 tutorial says rapid convergence after
  approximately 100 iterations occurs with aggressive multigrid and automatic
  CFL adaptation; its config still uses a large iteration ceiling.
- The SU2 turbulent ONERA M6 tutorial uses drag coefficient Cauchy convergence
  over 100 elements with `CONV_CAUCHY_EPS=1E-6` and a very large iteration
  ceiling.
- SU2 FAQ frames residual convergence as a desired log10 residual reduction.

## Current Main-Wing Verdict

- solver_execution: `executed`
- convergence_gate_status: `warn`
- convergence_comparability_level: `run_only`
- final_cl: `0.263161913`
- main_wing_lift_acceptance_status: `fail`
- engineering_verdict: `not_converged_engineering_evidence`

## HPA Main-Wing Engineering Requirements

- real main-wing geometry and mesh handoff
- `V=6.5 m/s`
- reference geometry gate pass
- force marker gate pass
- mesh quality acceptable for solver mode
- source-backed SU2 iteration budget and stopping criteria
- convergence gate pass
- `CL > 1.0` at `V=6.5 m/s`

## Next Actions

- `record_openvsp_main_wing_incidence_twist_camber_provenance`
- `treat_alpha_trim_probe_as_lift_slope_diagnostic_only`
- `define_source_backed_convergence_campaign_before_engineering_validation_claim`

## References

- https://su2code.github.io/docs_v7/Solver-Setup/
- https://su2code.github.io/docs/FAQ/
- https://su2code.github.io/tutorials/Inc_Inviscid_Hydrofoil/
- https://su2code.github.io/tutorials/Inviscid_ONERAM6/
- https://su2code.github.io/tutorials/Turbulent_ONERAM6/
