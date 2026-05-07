# Moment Closure Diagnosis

## Case

- target_main_tip_z_m: `2.000`
- recipe_id: `4a5b3187fd18`
- recipe_signature: `baseline_uniform|1.000000,1.000000,1.000000,1.000000,0.005000`
- tube_mass_kg: `16.030395`
- clearance_margin_m: `0.027652109`

## Finding

- Baseline reported moment residual: `1707.206` N*m.
- Baseline residual vector: Mx `-2.833`, My `-944.213`, Mz `1422.324` N*m.
- Cm-off residual drops to `246.776` N*m, with pitch residual My `-5.369` N*m.
- Cm sign-flip residual is `1316.944` N*m; it improves over baseline but still does not pass.
- Wire-off residual is `1788.627` N*m and tip deflection becomes `11.038` m.
- Equal rear/main stiffness gives `1570.859` N*m; rear 10x stiffness gives `2181.556` N*m.

## Engineering Interpretation

The canonical dual-beam model exposes aerodynamic pitching moment as `torque_per_span_nmpm` / `torque_about_main_per_span_nmpm`; the raw nondimensional airfoil Cm distribution is not retained at this layer. Therefore this debug validates torque ownership and closure wiring, not the upstream 2D Cm source quality.

The failure is dominated by load/reaction moment bookkeeping, not by tube mass or EI. Force closure and the linear equilibrium residual pass at numerical tolerance, while moment closure fails by O(10^3) N*m. Cm/torsion is a large contributor because turning Cm off removes most of the pitch-axis residual, but Cm-off still fails because the yaw/offset-link reaction channel leaves an O(10^2) N*m residual.

The current production load ownership applies aerodynamic torque as a main-beam My point moment. That torque is not distributed as a front/rear vertical couple, while the sparse offset rigid links and explicit truss wire create large self-equilibrated y-force paths. The closure diagnostic then tries to collapse all generalized constraint reactions into one global moment with a 1e-6 N*m tolerance. That is too strict for this currently mixed generalized-force bookkeeping channel.

## Direct Answers

- Is moment_closure fail caused mostly by Cm/torsion? `Partly yes`: Cm/torsion is the largest pitch-axis driver; Cm-off reduces the norm from `1707.2` to `246.8` N*m. But Cm-off still does not pass because the yaw/offset reaction channel remains.
- Does Cm-off pass? `No`; reported residual remains `246.776` N*m vs threshold `1.0e-06` N*m.
- Does changing rear spar stiffness or spar position help? `Not enough to pass`; equal stiffness `1570.9` N*m, rear 10x `2181.6` N*m.
- Is this likely a real structure problem or a code/wiring problem? `Mostly code/model bookkeeping until proven otherwise`; the exact solver equilibrium passes, and the failure moves strongly with torque ownership/post-processing choices.
- Next smallest fix before FEM: make moment closure a decomposed diagnostic with separate force equilibrium, pitch-torque ownership, and yaw/offset-link bookkeeping checks; then convert aerodynamic Cm to an explicit front/rear spar couple or documented torsional DOF path before using it as a hard structural blocker.
