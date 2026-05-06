# DAE11 Full-Polar Quality Audit And Rescue

## Verdict

DAE11 is not mission-grade because of `insufficient_safe_clmax_margin`, not because of missing Re coverage, missing roughness data, nonfinite Cd, or sidecar query extrapolation. The DAE11-only gap-fill added the root/mid1 Re envelope and a 0.25 deg alpha sweep, but DAE11 still remains `full_polar_candidate_not_mission_grade` with issues `insufficient_safe_clmax_margin`.

## Existing Archive Record

- record-level source_quality: `full_polar_candidate_not_mission_grade`
- root sidecar query-level source_quality: `not_mission_grade_sidecar`
- mid1 sidecar query-level source_quality: `not_mission_grade_sidecar`
- full-polar Re coverage: `100000.0` to `700000.0`, `17` Re stations
- full-polar Cl coverage: `-0.373815` to `1.706308`
- alpha coverage: `-6.0` to `18.0` deg
- clean/rough coverage: `clean;rough`
- convergence pass rate: `0.9819927971188476`
- finite Cd fraction: `1.0`
- negative/nonfinite Cd count: `0` / `0`
- quality warnings: `insufficient_safe_clmax_margin`
- exact Policy A not-mission-grade reason: selected DAE11 has record source_quality `full_polar_candidate_not_mission_grade`; sidecar maps that to `not_mission_grade_sidecar` even though the root/mid1 query work points do not extrapolate.

## Required Envelope Versus Existing DAE11 Data

Root envelope: Re `435930.330685` / `469514.093593` / `503097.856502`, Cl `1.497` / `1.527564` / `1.552016` / `1.558129`.

Mid1 envelope: Re `373368.002421` / `381788.095207` / `390208.187993`, Cl `1.400623` / `1.483199` / `1.54926` / `1.565775`.

The existing DAE11 grid already brackets these Re/Cl query points. `dae11_coverage_gap_report.csv` records each root/mid1 sidecar work point, its Re bracket, Cl bracket, and extrapolation flag.

All root/mid1 sidecar work points are inside the available clean pre-stall Cl branch at the bracketing Re stations, and rough data is present. The issue classification is therefore not coverage, convergence, roughness, Cd discontinuity, query-range extrapolation, or metadata; it is the conservative safe-clmax margin.

## Gap-Fill / Rescue Result

- gap-fill query count: `46`
- Re grid count: `23`
- alpha sweep: -6 to 18 deg, step 0.25 deg
- roughness modes: `clean;rough`
- convergence pass rate after gap-fill: `0.988122`
- finite/prestall polar point count after gap-fill: `3593`
- alpha_L0: `-6.037911` deg
- cl_alpha_per_rad: `5.896812`
- usable_clmax: `1.707961`
- safe_clmax: `1.487165`
- root/mid1 required max Cl: `1.565775`
- safe_clmax margin to mid1 Cl_max: `-0.07861`
- root mean Cd at work points: `0.011595`
- root Cd p90: `0.011619`
- root mean Cm at work points: `-0.135515`
- mid1 mean Cd at work points: `0.012768`
- mid1 Cd p90: `0.012855`
- mid1 mean Cm at work points: `-0.134893`
- roughness sensitivity mean Cd: `0.004706`

## Engineering Read

This is a stall-margin/quality-contract problem. DAE11 has attractive profile drag in the current sidecar operating points, but the quality contract requires safe_clmax headroom above the root/mid1 local-Cl envelope. The raw polar reaches higher usable Cl than the design Cl, but the conservative `safe_clmax = 0.90 * usable_clmax - 0.05` rule leaves DAE11 below the required root/mid1 envelope. That is why Policy A looks aerodynamically strong but remains not mission-grade.
