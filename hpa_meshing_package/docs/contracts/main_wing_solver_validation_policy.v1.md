# main_wing_solver_validation_policy.v1

`main_wing_solver_validation_policy.v1` separates software route smokes from
engineering convergence validation for the main-wing high-fidelity route.

## Purpose

Short SU2 runs are useful, but only for the right question:

- Route smoke: did `SU2_CFD` launch from a real handoff, write `history.csv`,
  preserve `V=6.5 m/s`, and feed the report/gate machinery?
- Diagnostic probe: does a bounded non-default run reveal a monotonic trend,
  a broken marker, a bad reference normalization, or a mesh/numerics symptom?
- Engineering convergence validation: can the result be treated as converged
  main-wing CFD evidence under an explicit convergence policy?

The first two are not convergence claims.

## Source-Backed Solver Policy

The SU2 solver documentation defines steady-state control by either `ITER` or
convergence criteria. It also supports residual stopping criteria and
coefficient Cauchy criteria; coefficient Cauchy checks require a specified
window such as `CONV_CAUCHY_ELEMS`.

Source-backed examples set much larger iteration ceilings than this route's
current smoke budgets:

- SU2 incompressible inviscid hydrofoil tutorial config uses `ITER=9999`,
  `CONV_FIELD=RMS_PRESSURE`, `CONV_RESIDUAL_MINVAL=-15`,
  `CONV_STARTITER=10`, and `CONV_CAUCHY_ELEMS=50`.
- SU2 inviscid ONERA M6 tutorial notes rapid convergence after approximately
  100 iterations only with aggressive multigrid and automatic CFL adaptation;
  its config still uses `ITER=9999` and residual stopping.
- SU2 turbulent ONERA M6 tutorial uses coefficient convergence for drag with
  `CONV_CAUCHY_ELEMS=100`, `CONV_CAUCHY_EPS=1E-6`, and an iteration ceiling of
  `ITER=999999`.
- SU2 FAQ frames residual convergence as a desired reduction, commonly using
  reductions such as six orders of magnitude.

Therefore a 12/40/80-iteration main-wing run can be route evidence or trend
evidence, but it is not enough by itself to define engineering convergence.

## HPA Main-Wing Acceptance Rules

A main-wing solver result may be called engineering-converged only when all of
the following are true:

1. The run is from real main-wing geometry and a real `mesh_handoff.v1`.
2. `su2.flow_conditions` or resolved runtime fields preserve the HPA standard
   `V=6.5 m/s`.
3. Reference geometry and force-marker provenance gates pass.
4. Mesh quality is acceptable for the intended solver mode; warn-level mesh
   quality remains a blocker for engineering validation.
5. The SU2 convergence setup is source-backed and recorded, using residual and
   coefficient criteria appropriate for the case.
6. The observed history passes the project convergence gate and the solver
   budget is not just a smoke budget.
7. At `V=6.5 m/s`, main-wing lift acceptance passes: `CL > 1.0`.

`convergence_gate.v1` remains useful as a baseline comparability contract, but
its default `min_iterations=20` and `tail_window=10` are not a final engineering
validation budget. A pass at that layer can only promote to preliminary
comparison after the solver-validation policy is satisfied.

## Current Route Interpretation

The current main-wing OpenVSP-reference 80-iteration artifact is:

- solver executed
- `V=6.5 m/s`
- `alpha=0 deg`
- `CL ~= 0.2632`
- `convergence_gate_status=warn`
- `convergence_comparability_level=run_only`

That artifact is a useful smoke and diagnostic result. It must not be reported
as converged CFD. The correct next engineering step is not to blindly increase
iterations; it is to choose a bounded validation plan:

1. Record OpenVSP incidence/twist/camber provenance so alpha-zero lift is
   interpreted correctly.
2. If needed, run a small alpha/trim sanity probe as lift-slope diagnostics
   only, not as convergence validation.
3. Define a source-backed convergence campaign budget and stopping criteria
   before claiming engineering convergence.

## References

- SU2 Solver Setup: https://su2code.github.io/docs_v7/Solver-Setup/
- SU2 FAQ: https://su2code.github.io/docs/FAQ/
- SU2 Inviscid Hydrofoil tutorial:
  https://su2code.github.io/tutorials/Inc_Inviscid_Hydrofoil/
- SU2 Inviscid ONERA M6 tutorial:
  https://su2code.github.io/tutorials/Inviscid_ONERAM6/
- SU2 Turbulent ONERA M6 tutorial:
  https://su2code.github.io/tutorials/Turbulent_ONERAM6/
