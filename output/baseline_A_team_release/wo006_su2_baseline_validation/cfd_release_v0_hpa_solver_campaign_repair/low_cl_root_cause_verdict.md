# Low-CL Root-Cause Verdict

Verdict: `not_a_stable_low_cl_case_yet`

The original `CL_primary≈0.858` value was not a converged aerodynamic result.
It came from a 160-iteration smoke/probe run and the extended Coarse history
continued rising:

- iteration 160: `CL_primary=0.8584368`
- iteration 500: `CL_primary=0.9571043`
- iteration 1000: `CL_primary=1.074658`

The Phase 2 diff did not identify a proven physical setup mismatch in the locked
comparison basis. The new Coarse case matches the reference in:

- `rhoInf=1.225`
- `nu=1.4607e-05`
- `magUInf=6.5`
- inlet/farfield velocity direction for `AoA=0.18 deg`
- `Aref=33.420059598`
- `lRef=1.003721543`
- `dragDir` / `liftDir`
- `RAS/SpalartAllmaras`
- primary force patches `airfoil_upper airfoil_lower`
- total artificial closure accounting policy

Geometry and patch-area evidence also does not support a gross geometry
mistake: upper/lower airfoil surface areas match the stored reference within
the report tolerance. The major remaining differences are mesh-family
discretization/topology, patch face counts, the added `total_physical` force
object, potentialFoam startup, and the fact that the new Coarse force history is
still not converged by the requested gate.

Exact blocker:

The Coarse grid-family baseline does not reach a stable final-100 force window
by 1000 iterations and does not reproduce the known reference force level.
Therefore the campaign must not proceed to Medium/Fine yet. The next bounded
work must stay on Coarse and address solver convergence or the Coarse mesh
baseline before any grid-independence claim is attempted.
