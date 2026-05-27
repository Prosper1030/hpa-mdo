# Transition SST LM Tu0p5 Diagnostic

Verdict: `not usable due to instability / no evolved transition field written`

- reason: the solver was terminated after unstable force drift before a converged transition field was written
- case: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_transition_sst_lm/openfoam_cases/case_transitionSST_LM_Tu0p5`
- latest saved field time analyzed: `2000`
- force history reached: `2061`
- model: `kOmegaSSTLM` Langtry-Menter gamma-ReTheta Transition SST
- source BC pattern: OpenFOAM-v2512 `tutorials/incompressible/simpleFoam/T3A`, adapted to this case's `farfield`/`outlet` convention.
- preserved refs: `U=6.5 m/s`, `rhoInf=1.225`, `nu=1.4607e-05`, `AoA=0.18 deg`, `lRef=1.003721543`, `Aref=33.420059598`.
- transition inlet values: `Tu=0.5%`, `k=0.001584375 m2/s2`, `c_ref=1.003721543 m`, `L=0.07026050801 m`, `omega=1.03432513267 1/s`, `ReThetat=879.6744`, `gammaInt=1`.
- omega bounding warnings: `62`; largest reported omega max: `3.99156e+20`.
- CD/CL numbers below are the last unstable force samples, not accepted converged coefficients.

## SA Fine vs Transition

| quantity | SA Fine | transition Tu0p5 | delta % |
|---|---:|---:|---:|
| `CD_total_physical` | 0.03326556 | 0.03870323 | 16.346 |
| `CD_primary` | 0.03320877 | 0.03871308 | 16.575 |
| `CL_primary` | 1.160934 | 1.194993 | 2.934 |
| `CD_pressure_total_physical` | 0.022950014 | 0.034050666 | 48.369 |
| `CD_viscous_total_physical` | 0.010315548 | 0.0046525709 | -54.897 |

## yPlus

| patch | mean | max | % < 1 | % < 5 | % > 20 |
|---|---:|---:|---:|---:|---:|
| `airfoil_upper` | 0.833712 | 3.11444 | 58.681 | 100.000 | 0.000 |
| `airfoil_lower` | 0.755823 | 2.79542 | 92.126 | 100.000 | 0.000 |
| `te_wall` | 1.26541 | 1.72123 | 15.865 | 100.000 | 0.000 |
| `physical_tip_left` | 40.3429 | 42.363 | 1.250 | 1.250 | 98.750 |
| `physical_tip_right` | 40.3429 | 42.363 | 1.250 | 1.250 | 98.750 |

## Transition Fields

The listed transition fields are the saved initialization fields at time 2000. The unstable continuation reached the force log at later iterations, but no evolved gamma/ReTheta/nut field was written before termination.
- gammaInt mean/min/max: `1.0` / `1.0` / `1.0`
- gammaInt volume fractions: `<0.1 None%`, `<0.5 None%`, `>0.9 None%`
- ReThetat mean/min/max: `879.6744` / `879.6744` / `879.6744`
- nut/nu mean/max: `None` / `None`

## Engineering Read

- Primary airfoil/TE yPlus is in a reasonable near-wall range for a transition-model diagnostic, but the physical tip closure walls are not.
- The unstable transition run does not support claiming a drag reduction relative to SA/Fine. The last force sample shows higher CD and much higher pressure-drag split, while omega behavior is not physically trustworthy.
- Because the evolved gammaInt field was not written, transition location, laminar separation bubble behavior, and TE pressure-drag localization remain unanswered.
- Saved-field Cp internal summary: min/mean/max `-1.8240426035502957` / `-0.0879216383103263` / `1.089368047337278`.
- Wall-shear patch summaries were written for `5` wall patches.
