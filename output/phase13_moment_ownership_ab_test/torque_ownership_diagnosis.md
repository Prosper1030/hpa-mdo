# Torque Ownership Diagnosis

## Case

- target_main_tip_z_m: `2.000`
- recipe_id: `4a5b3187fd18`
- recipe_signature: `baseline_uniform|1.000000,1.000000,1.000000,1.000000,0.005000`
- tube_mass_kg: `16.030395`
- baseline_clearance_margin_m: `0.027652109`

## Mode Results

| mode | force residual N | Mx N*m | My N*m | Mz N*m | XY N*m | total N*m | tip z m | clearance m | interpretable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `main_beam_my_about_main_spar` | 1.171e-08 | -2.833 | -944.213 | 1422.324 | 944.217 | 1707.206 | 1.604 | 0.027652 | False |
| `front_rear_vertical_couple` | 1.826e-08 | -2.903 | 105.733 | 1522.190 | 105.773 | 1525.861 | 1.575 | 0.032232 | True |
| `cm_off_baseline` | 2.950e-08 | 2.657 | -5.369 | 246.703 | 5.991 | 246.776 | 1.735 | 0.065186 | False |
| `current_legacy_mode` | 1.171e-08 | -2.833 | -944.213 | 1422.324 | 944.217 | 1707.206 | 1.604 | 0.027652 | False |

## Diagnosis

- Smallest physically meaningful residual among the tested modes is `front_rear_vertical_couple` at `1525.861` N*m.
- If Mz is treated as report-only pending offset-link validation, `front_rear_vertical_couple` has XY residual `105.773` N*m.
- Current legacy all-axis scalar residual is `1707.206` N*m.
- Cm-off control residual is `246.776` N*m, so aerodynamic torque ownership is a major contributor but not the only bookkeeping issue.
- The raw nondimensional airfoil Cm distribution is not available at this dual-beam layer; this A/B tests torque-per-span ownership, not the upstream 2D Cm source quality.

## Explicit Answers

- Which torque ownership mode gives the smallest physically meaningful residual? `front_rear_vertical_couple`.
- Is current legacy moment_closure definition too strict or incorrectly wired? `Yes for production gating`: it mixes pitch torque closure with yaw/offset-link generalized-force bookkeeping and uses a 1e-6 N*m all-axis norm.
- Can the 16 kg recipe be considered structurally plausible pending FEM? `Yes, plausible but not structure-grade`: force equilibrium, clearance, and wire validity are good, while moment ownership remains unresolved.
- What should production_hard_feasible use until this is fixed? Use `inverse_feasible AND clearance_feasible AND wire_feasible AND geometry_validity AND force/equilibrium/compatibility/conditioning`; keep decomposed moment closure as diagnostic/report-only until torque ownership is validated.

## Bookkeeping Bug Checks

| check | evidence | assessment |
|---|---|---|
| wrong sign of Cm | Cm-off reduces My from large residual to near zero; sign-flip was checked in Phase 13 debug and did not pass. | possible sign convention issue, not sole cause |
| moment arm from wrong reference | front/rear couple changes My strongly while spar x shifts only had modest effect in prior debug. | not primary, but torque reference should be documented |
| full-span vs half-span factor | force residual is near numerical zero and residuals do not show 2x-only behavior. | unlikely |
| front/rear spar swapped | front/rear couple remains stable and improves My rather than exploding. | unlikely as sole cause |
| link moment double counted | Mz remains dominant and is tied to offset-link generalized reactions. | likely audit target |
| root reaction moment omitted | root contribution is explicitly included in `moment_axis_breakdown.csv`. | not omitted in this diagnostic |
| wire reaction moment omitted | wire contribution is explicitly included and wire path changes deflection strongly. | not omitted in this diagnostic |
| aerodynamic Cm at wrong station | raw Cm is not retained here; only torque-per-span ownership can be audited. | upstream Cm station mapping still needs separate audit |
