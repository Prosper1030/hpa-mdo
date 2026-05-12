# Control Interface Pack

Baseline A keeps all-moving H-tail/V-tail in the current screening closure.

## Current Screening Basis

- Managed CG: `0.75 m`.
- Tail trim/stability status: `pass`.
- H-tail required deflection: `10.55562073792222 deg`.
- Static margin: `0.092835`.
- C_n_beta: `0.014556`.

## Open Work

- Build a control derivative matrix from the current full-aircraft basis.
- Check tail motor/servo authority and rate margin.
- Add tailboom and vertical strut first-order load/stiffness model.
- Preserve the rule that uncompensated CG is rejected.
