# RERUN

From `/Volumes/Samsung SSD/hpa-mdo`:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_true_baseline_domain_convention_fix.py \
  --source-case '/Volumes/Samsung SSD/hpa-mdo/.claude/worktrees/vibrant-meninsky-c9e255/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_bay_gate/openfoam_cases/fullwing_debug/swept_cgrid' \
  --output-dir '/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_domain_convention_fix' \
  --clean
```

The runner copies the accepted true Baseline swept C-grid `polyMesh`, renames
the y=0 `tip_left` metadata to `root_symmetry`, sets it to `symmetryPlane`, uses
half-wing Sref for forceCoeffs, excludes root symmetry from all forces, and
reruns only the same operating-point route-smoke.
