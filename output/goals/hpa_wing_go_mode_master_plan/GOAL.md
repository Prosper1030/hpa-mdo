# HPA Wing Go Mode Goal

## Final Objective

Find a structure-feasible, aerodynamically efficient, production-facing HPA main
wing candidate for the Birdman-style mission.

The final candidate must connect the whole engineering chain:

```text
mission / power budget
-> spanload design
-> Fourier-AVL spanload control
-> smooth production geometry
-> AVL actual CDi and local Cl/Re
-> dual-beam jig-shape and tube-mass feasibility
-> Tier2 full-alpha airfoil selection
-> aero-structure closure
-> structural trust label and FEM spot-check plan
-> production-facing recommendation
```

## Desired Outcome

Codex Go Mode should continue working until it reaches one of two outcomes:

1. **Production-facing candidate found**
   - A candidate satisfies the success criteria below and is packaged with the
     artifacts needed for engineering review.

2. **Blocker proven**
   - Codex proves which physical or modeling blocker prevents the goal, with
     evidence strong enough to decide the next engineering direction.

Do not stop merely because an intermediate report exists. Reports are evidence,
not the goal.

## Production-Facing Candidate Success Criteria

### Mission / Power

- Report nominal `P_crank`.
- Report conservative `P_crank`.
- Include main-wing `CDi`, profile drag, nonwing reserve, propeller efficiency,
  and drivetrain efficiency.
- Apply conservative CDi / closure margin where appropriate.
- Preferred target: nominal `P_crank <= 180 W` and conservative
  `P_crank <= 190 W`.
- If a physically credible candidate misses this band, report it as a
  compromise candidate, not a production-facing success.

### Geometry

- Smooth monotone production geometry.
- No faceted chord as final production geometry.
- VSP `production_inspection` export exists.
- AVL parity export exists.
- Chord slope / curvature diagnostics are reported.

### Spanload

- Fourier target and AVL actual spanload are aligned within tolerance, or the
  mismatch is corrected through a measured Fourier-AVL bridge.
- If not alignable, Codex must prove what authority is missing:
  chord, twist, airfoil alpha_L0/camber, loaded dihedral, AVL reference setup,
  or another documented cause.

### Structure / Loaded Shape

- Prioritize total cruise effective dihedral around `6-7 deg` if physically
  achievable.
- If `6-7 deg` cannot meet mass, clearance, or wire constraints, find the
  nearest practical compromise and quantify the penalty.
- Loaded-Z definitions must be explicit:
  aerodynamic surface z, beam-line z, built-in z, elastic z, and total loaded z.
- Jig shape must have healthy clearance or a quantified, explicitly accepted
  compromise.

### Structure Budget

- Target spar/tube mass around `10.5-11.5 kg` class if physically achievable.
- If impossible, find the minimum credible mass and explain why.
- Clearance, wire, geometry, and force closure must pass.
- Moment closure must be split into physical moment balance and bookkeeping
  diagnostics; unresolved bookkeeping must not be blindly used as a hard fail.

### Airfoil

- Use Tier2 full-alpha database after the feasible loaded shape and AVL actual
  `Cl/Re` envelope are known.
- Separate raw best and conservative best.
- Repair query warnings or explicitly reject the warning-bearing assignment.
- A production-facing airfoil assignment must have acceptable query quality.

### Closure

- After airfoil selection, rerun AVL and structural checks.
- If spanload, deflection, power, mass, clearance, or wire changes too much,
  loop back automatically.
- Closure must report mismatch tolerances and status.

### Validation

- Internal dual-beam / tube model may be used for daily screening.
- CalculiX / APDL / corrected shell FEM should be used only for selected
  candidates or model calibration, not broad search.
- Trust labels must be explicit:
  daily screening, diagnostic FEM-supported, FEM spot-check required, or final
  structure-grade.

## Non-Goals

- Do not run broad aero optimization just to produce more rows.
- Do not change production ranking unless the goal explicitly reaches a
  production-facing recommendation step with evidence.
- Do not add hard gates during exploration.
- Do not rerun broad CST/NSGA unless a documented blocker proves the Tier2
  database cannot cover the required `Cl/Re` envelope.
- Do not treat high-Z low-mass escape states as winners without AVL,
  manufacturability, and closure evidence.
- Do not treat FEM as the main search engine.
- Do not call a report-only diagnostic a solved design.
