# OpenFOAM Patch Inventory

- source case: `/Volumes/Samsung SSD/hpa-mdo/.claude/worktrees/vibrant-meninsky-c9e255/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_bay_gate/openfoam_cases/fullwing_debug/swept_cgrid`
- source commit: `35dfadb0`
- primary surface names: `airfoil_upper/airfoil_lower`
- farfield patches: `['farfield']`
- inlet patches: `[]`
- outlet patches: `['outlet']`

| patch | boundary type in accepted mesh | nFaces | role |
|---|---:|---:|---|
| `airfoil_upper` | `wall` | 7488 | solid wall |
| `airfoil_lower` | `wall` | 7488 | solid wall |
| `te_wall` | `wall` | 624 | solid wall / diagnostic force patch |
| `outlet` | `patch` | 624 | flow boundary |
| `farfield` | `patch` | 14976 | flow boundary |
| `tip_left` | `patch` | 12800 | solid wall / diagnostic force patch |
| `tip_right` | `patch` | 12800 | solid wall / diagnostic force patch |

Note: `tip_left` and `tip_right` are reported with their accepted mesh boundary type, then converted to OpenFOAM `wall` class in the generated solver case without changing face topology.
