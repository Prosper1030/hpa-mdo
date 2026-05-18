# forceCoeffs Setup Report

- primary group: `airfoil_upper + airfoil_lower`
- diagnostic groups are separate and not merged into one `wing_wall`
- `forces` functionObjects are also enabled for pressure/viscous split
- `Cd(f)` / `Cd(r)` from `forceCoeffs` are front/rear components, not pressure/viscous split

| group | patches |
|---|---|
| `primary` | `['airfoil_upper', 'airfoil_lower']` |
| `te_wall` | `['te_wall']` |
| `tip_left` | `['tip_left']` |
| `tip_right` | `['tip_right']` |
| `total` | `['airfoil_upper', 'airfoil_lower', 'tip_left', 'tip_right', 'te_wall']` |
