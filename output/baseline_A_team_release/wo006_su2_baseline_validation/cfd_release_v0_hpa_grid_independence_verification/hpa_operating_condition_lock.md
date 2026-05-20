# HPA Operating Condition Lock

Verdict: `current_openfoam_basis_locked_for_hpa_verification`

This supersedes the earlier Phase 0 hard-stop wording. The current CFD
verification basis is the recent successful OpenFOAM full-wing mirror route,
not the older AVL/Tier2 screening drag-power basis.

## Current CFD Basis

- source commit: `fe73939a`
- rho: `1.225 kg/m^3`
- viscosity: `nu=1.4607e-05 m^2/s`, `mu=1.7893575e-05 Pa*s`
- V: `6.5 m/s`
- AoA: `0.18 deg`
- Sref: `33.420059598 m^2`
- Cref: `1.003721543 m`
- CL_design target: `1.16853`
- chord range: `0.645004..1.256773 m`
- Re range along span: `287022..559254`
- full-wing / half-wing convention: `full-wing mirror route`
- turbulence / transition model: `SpalartAllmaras`, no transition model
- force definitions: `primary = airfoil_upper + airfoil_lower; total includes physical_tip_left/right and te_wall`
- stable route-smoke CL/CD: `CL_primary=1.133291`, `CD_primary=0.03276165`

## Historical Comparison Basis

The old `rho=1.18/V=6.6` basis remains historical comparison only: `CL_design=1.16853`,
`CD_total=0.026020030502038057`, `P_crank=174.60027944116567 W`.
The difference is documented, but it does not hard-stop the current OpenFOAM route because
the latest instruction is to continue from the recent successful commits. Do not return to
`rho=1.18/V=6.6` as a hard stop unless the user explicitly asks for a new
screening-basis sensitivity study.

## Engineering Caveat

Fully turbulent Spalart-Allmaras is acceptable as the current route-smoke and
grid-family basis because that is what recently stabilized. It is not final
low-Re HPA transition truth. Any final drag claim still needs Cp, Cf, wake,
tip-vortex, and transition/separation behavior checks.
