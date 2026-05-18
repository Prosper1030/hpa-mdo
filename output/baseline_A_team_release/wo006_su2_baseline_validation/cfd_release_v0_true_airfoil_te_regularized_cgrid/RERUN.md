# RERUN

```bash
PYTHONPATH=scripts:hpa_meshing_package/src ./.venv/bin/python \
  scripts/run_wo006_true_airfoil_te_regularized_cgrid.py \
  --clean \
  --output-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_te_regularized_cgrid \
  --n-perim 192 \
  --n-radial 64 \
  --farfield-chords 10.0 \
  --wake-length-chords 8.0
```
