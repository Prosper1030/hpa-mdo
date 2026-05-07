# Feasibility Logic Report

Phase 13 keeps aerodynamic ranking and production hard gates unchanged. It only fixes the diagnostic structural-selector labels used by this z-state sweep.

Definitions used in the output tables:

- `inverse_feasible`: the canonical inverse-jig workflow's loaded-shape / clearance / manufacturing feasibility signal from `candidate.overall_feasible`.
- `clearance_feasible`: inverse-design jig ground clearance passes, using `ground_clearance_passed` or nonnegative `jig_ground_clearance_margin_m`.
- `wire_feasible`: dual-beam production wire-support validity passes.
- `moment_closure_feasible`: dual-beam production numerical-consistency moment closure passes.
- `geometry_validity`: candidate geometry validity passes in the inverse and production candidate payload.
- `production_hard_feasible = clearance_feasible AND wire_feasible AND moment_closure_feasible AND geometry_validity`.

`overall_feasible` from older canonical summaries must be read as `inverse_feasible`. It is not allowed to imply production structural feasibility when `moment_closure_feasible=False`.
