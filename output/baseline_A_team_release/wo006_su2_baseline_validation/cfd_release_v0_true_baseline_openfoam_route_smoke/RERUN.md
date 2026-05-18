# RERUN

From `/Volumes/Samsung SSD/hpa-mdo`:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_true_baseline_openfoam_route_smoke.py \
  --source-case '/Volumes/Samsung SSD/hpa-mdo/.claude/worktrees/vibrant-meninsky-c9e255/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_bay_gate/openfoam_cases/fullwing_debug/swept_cgrid' \
  --output-dir '/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_openfoam_route_smoke' \
  --clean
```

The runner copies the accepted polyMesh from the source case and only regenerates
OpenFOAM boundary-condition dictionaries, functionObjects, validation reports,
and solver logs. It does not rerun section, bay, geometry, TE-gap, or mesh-topology
generation.
