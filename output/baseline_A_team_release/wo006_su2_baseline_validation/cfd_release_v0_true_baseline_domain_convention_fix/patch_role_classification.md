# Patch Role Classification

- mesh identity: `half-wing`
- root symmetry original patch: `tip_left`
- physical tip original patches: `['tip_right']`

| original patch | corrected patch | role | original type | nFaces |
|---|---|---|---|---:|
| `airfoil_upper` | `airfoil_upper` | `main_lifting_wall_upper` | `wall` | 7488 |
| `airfoil_lower` | `airfoil_lower` | `main_lifting_wall_lower` | `wall` | 7488 |
| `te_wall` | `te_wall` | `trailing_edge_wall` | `wall` | 624 |
| `outlet` | `outlet` | `farfield_or_inlet_outlet` | `patch` | 624 |
| `farfield` | `farfield` | `farfield_or_inlet_outlet` | `patch` | 14976 |
| `tip_left` | `root_symmetry` | `root_symmetry` | `patch` | 12800 |
| `tip_right` | `physical_tip` | `physical_tip_wall` | `patch` | 12800 |
