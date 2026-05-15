# Rerun Instructions

```bash
.venv/bin/python scripts/run_wo006_structured_hexa_verification.py \
  --output-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_structured_hexa_verification \
  --openfoam /opt/homebrew/bin/openfoam \
  --clean
```

Use `--skip-verification` to rerun only the artificial and debug gates.
