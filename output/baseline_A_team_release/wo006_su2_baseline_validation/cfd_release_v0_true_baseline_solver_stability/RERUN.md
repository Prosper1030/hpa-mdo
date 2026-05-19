# RERUN

From `/Volumes/Samsung SSD/hpa-mdo`:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_true_baseline_solver_stability.py \
  --source-case '/Volumes/Samsung SSD/hpa-mdo/.claude/worktrees/vibrant-meninsky-c9e255/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_bay_gate/openfoam_cases/fullwing_debug/swept_cgrid' \
  --corrected-case '/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_domain_convention_fix/openfoam_cases/true_baseline_swept_cgrid_halfwing_convention' \
  --output-dir '/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_solver_stability' \
  --clean
```

This runner audits the corrected root-symmetry patch, records bounded half-wing
diagnostic evidence, switches to OpenFOAM `mirrorMesh` if the half-wing decision
gate trips, and runs only the same operating-point route-smoke. It does not run
an AoA sweep, compare to XFOIL, or regenerate the accepted C-grid mesh.
