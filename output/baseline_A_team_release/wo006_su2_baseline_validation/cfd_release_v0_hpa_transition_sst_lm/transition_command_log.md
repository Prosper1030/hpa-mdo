# WO-006 Transition SST LM Tu0p5 Command Log

Case:
`/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_transition_sst_lm/openfoam_cases/case_transitionSST_LM_Tu0p5`

Source Fine case:
`/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup/openfoam_cases/fine/fullwing_artificial_tip_symmetry`

## Model Availability

```sh
simpleFoam -listTurbulenceModels | grep -i -E "kOmegaSSTLM|transition|Langtry|gamma|ReTheta"
```

Direct invocation failed because `simpleFoam` was not on the host shell path. The OpenFOAM wrapper from `/tmp` succeeded and confirmed `kOmegaSSTLM` is available.

```sh
/opt/homebrew/bin/openfoam -c 'pwd; command -v simpleFoam; simpleFoam -listTurbulenceModels | grep -i -E "kOmegaSSTLM|transition|Langtry|gamma|ReTheta"'
```

## Native Tutorial Source

```sh
/opt/homebrew/bin/openfoam -c 'printf "FOAM_TUTORIALS=%s\n" "$FOAM_TUTORIALS"; find "$FOAM_TUTORIALS" \( -iname "*T3A*" -o -iname "*kOmegaSSTLM*" -o -iname "*transition*" \) | sed -n "1,200p"'
```

Native source used:
`/Volumes/OpenFOAM-v2512/tutorials/incompressible/simpleFoam/T3A`

## Validation And Run

```sh
/opt/homebrew/bin/openfoam -c 'checkMesh -case /tmp/hpa_transition_case -meshQuality > /tmp/hpa_transition_case/log.checkMesh_transition 2>&1'
/opt/homebrew/bin/openfoam -c 'simpleFoam -case /tmp/hpa_transition_case -dry-run -noFunctionObjects > /tmp/hpa_transition_case/log.simpleFoam_dry_run_transition 2>&1'
/opt/homebrew/bin/openfoam -c 'simpleFoam -case /tmp/hpa_transition_case > /tmp/hpa_transition_case/log.simpleFoam_transition_2200 2>&1'
```

The run was terminated manually after force drift and repeated extreme `omega` bounding. Force history reached iteration 2061; no evolved transition field time beyond 2000 was written.

## Post-Processing

```sh
/opt/homebrew/bin/openfoam -c 'simpleFoam -case /tmp/hpa_transition_case -postProcess -func yPlus -latestTime > /tmp/hpa_transition_case/log.simpleFoam_postProcess_yPlus_transition 2>&1'
/opt/homebrew/bin/openfoam -c 'simpleFoam -case /tmp/hpa_transition_case -postProcess -func wallShearStress -latestTime > /tmp/hpa_transition_case/log.simpleFoam_postProcess_wallShearStress_transition 2>&1'
python3 scripts/analyze_wo006_transition_sst_lm.py \
  --case-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_transition_sst_lm/openfoam_cases/case_transitionSST_LM_Tu0p5 \
  --out-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_transition_sst_lm \
  --sa-grid-csv output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/grid_family_results.csv
```

## OpenFOAM Case Files Changed

- `constant/turbulenceProperties`
- `system/fvSchemes`
- `system/fvSolution`
- `system/controlDict`
- `2000/k`
- `2000/omega`
- `2000/nut`
- `2000/gammaInt`
- `2000/ReThetat`

## Key Logs And Outputs

- `log.checkMesh_transition`
- `log.simpleFoam_dry_run_transition`
- `log.simpleFoam_transition_2200`
- `log.simpleFoam_postProcess_yPlus_transition`
- `log.simpleFoam_postProcess_wallShearStress_transition`
- `postProcessing/forceCoeffs_total_physical/2000/coefficient.dat`
- `postProcessing/forces_total_physical/2000/force.dat`
- `2000/yPlus`
- `2000/wallShearStress`
