# Error-Source Diagnosis Framework

## Use This Decision Tree In Order

Do not jump to calibration factors first. Move benchmark by benchmark.

## If Benchmark 1 Fails

Likely causes:

- wrong `E`, `G`, `rho`, or unit conversion
- wrong `R` or `t` interpretation
- wrong cantilever root boundary condition
- wrong distributed-load to nodal-load conversion
- half-span versus full-span bookkeeping error

First checks:

- compare against the closed-form cantilever formula
- verify beam mass from `rho A L`
- verify total root reaction equals total applied load
- inspect whether the external deck and internal model both use the same length units

Engineering read:

- If Benchmark 1 fails, do not interpret any two-beam result yet.
- The problem is still at the “basic beam contract” level.

## If Benchmark 1 Passes But Benchmark 2 Fails

Likely causes:

- tapered `EI` integration error
- segment-to-element mapping error
- midpoint versus nodal property interpolation mismatch
- wrong taper definition in the external deck

First checks:

- compare per-segment `R`, `t`, `A`, and `I`
- compare internal element-center properties against exported beam-section properties
- verify that the same taper law is applied in both models

Engineering read:

- This usually means the core beam math is fine but the spanwise property mapping is not.
- Do not call this a dual-beam physics problem yet.

## If Benchmark 2 Passes But Benchmark 3 Fails

Likely causes:

- front/rear load-sharing mismatch
- rigid-link kinematics mismatch
- spar separation or geometry-reference mismatch
- explicit two-beam model disagreeing with the equivalent collapsed section

First checks:

- compare main-tip and rear-tip deflection separately
- inspect whether links are equal-DOF or offset-rigid in both models
- check whether the external model uses joint-only links or an effectively denser coupling
- verify that lift is only on the main spar in both models

Engineering read:

- This is the first rung where a real model-form difference can appear.
- A failure here is meaningful, but it still says nothing yet about wire or torque.

## If Benchmark 3 Passes But Benchmark 4 Fails

Likely causes:

- wire stiffness mismatch
- pretension mismatch
- tension-only versus always-active support mismatch
- wire attachment point mismatch
- support represented as a single point in one model and a cluster or patch in the other

First checks:

- compare wire reaction or wire tension directly
- compare unstretched length, reference length, and pretension assumptions
- verify whether the external solver allows slack or only linear support behavior
- check whether the wire acts along the cable axis or only as a vertical constraint

Engineering read:

- This is not a reason to edit beam equations yet.
- It usually points to support representation, not beam bending math.

## If Benchmark 4 Passes But Benchmark 5 Fails

Likely causes:

- torque ownership mismatch
- wrong sign convention on `Cm` or torsional moment
- wrong moment reference location
- `My` point-moment path versus front/rear force-couple path mismatch
- external production deck silently omitting the torque channel

First checks:

- compare three ownership variants on the same geometry:
  - `main_beam_my_about_main_spar`
  - `front_rear_vertical_couple`
  - `Cm off`
- verify whether the external deck actually applies `MY`, `FZ` couples, or neither
- compare moment residual by axis rather than only one scalar norm
- verify half-span/full-span normalization of the torque data

Engineering read:

- This is the rung where the current repo is already waving a red flag.
- Do not fit a calibration factor until this contract is explicit.

## If Benchmarks 1 To 5 Pass But The Production-Like Case Fails

Likely causes:

- real load replay mismatch from `spar_data.csv` or other load artifacts
- wrong frozen case selection
- geometry export artifact
- support completeness issue
- shell-mesh artifact
- composite-section simplification or hardware-mass bookkeeping difference

First checks:

- verify that the frozen production case really reuses the intended evidence root
- compare beam-only external results before blaming shell-mesh results
- compare support reaction first, then tip deflection
- check whether the case uses the same torque ownership contract frozen in Benchmark 5

Engineering read:

- If all lower rungs pass, a production-case failure is finally informative.
- At that point the likely causes are case-specific load replay, support completeness, or higher-order model-form differences.

## If The Shell-Plus-Beam CalculiX Spot-Check Fails While Beam Benchmarks Pass

Likely causes:

- STEP quality
- Gmsh healing side effects
- shell normals or duplicate shell facets
- lack of volume elements
- support patch heuristics

First checks:

- inspect `mesh_diagnostics`
- check `analysis_reality`
- check whether the run is still `shell_plus_beam`
- check whether the run is only `LIMITED` or `NOT_COMPARABLE`

Engineering read:

- This is a shell-route problem, not automatically a beam-model calibration problem.

## Hard Stop Rules

Stop and write a report instead of tuning factors when any of these happen:

- Benchmark 1 or 2 fails.
- Torque ownership in Benchmark 5 is still ambiguous.
- External solver availability forces a surrogate that changes the physical question.
- A proposed factor would hide a known BC or load-contract mismatch.
- A proposed change would alter production ranking, hard gates, or `dual_beam_production` equations without explicit authorization.
