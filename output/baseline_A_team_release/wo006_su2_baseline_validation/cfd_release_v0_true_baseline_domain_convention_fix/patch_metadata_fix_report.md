# Patch Metadata Fix Report

- topology edit: none
- edited metadata: patch names/classes in `constant/polyMesh/boundary` only
- reason: original `tip_left` is the y=0 root plane in a half-wing domain

| original patch | corrected patch | role | generated boundary class |
|---|---|---|---|
| `airfoil_upper` | `airfoil_upper` | `main_lifting_wall_upper` | `wall` |
| `airfoil_lower` | `airfoil_lower` | `main_lifting_wall_lower` | `wall` |
| `te_wall` | `te_wall` | `trailing_edge_wall` | `wall` |
| `outlet` | `outlet` | `farfield_or_inlet_outlet` | `patch` |
| `farfield` | `farfield` | `farfield_or_inlet_outlet` | `patch` |
| `tip_left` | `root_symmetry` | `root_symmetry` | `symmetryPlane` |
| `tip_right` | `physical_tip` | `physical_tip_wall` | `wall` |

- corrected domain geometry note: `tip_left is exactly y=0 plane while tip_right is y=17.166143 plane; this looks like a half-span/root-symmetry domain, not a +/- full-span wing.`
