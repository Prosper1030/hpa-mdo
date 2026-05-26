# OpenFOAM CD Breakdown

## Scope

This audit uses the accepted Fine result as the current CFD reference:

- `CL_primary=1.160934`
- `CD_total_physical=0.03326556`

No new grid refinement or new CFD was run for this report.

Primary sources:

- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/grid_family_results.csv`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/grid_independence_aero_comparison.md`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_solver_report.md`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_final_window_stability.md`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_yplus_report.md`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_grid_independence_verification/hpa_cfd_verification_manifest.json`

## Fine reference

| Quantity | Value |
|---|---:|
| Grid | fine |
| Cells | 6,090,240 |
| CL_primary | 1.160934 |
| CD_primary | 0.03320877 |
| CD_total_physical | 0.03326556 |
| CmPitch_primary | -0.1322822 |
| yPlus primary mean / p95 / max | 0.8026 / 1.5226 / 3.1218 |
| CD_total_physical final-100 drift | 0.5241% |

Force definition from the current CFD basis:

- `primary = airfoil_upper + airfoil_lower`
- `total_physical = primary + te_wall`
- `physical_tip_left/right` are diagnostics and are excluded from `total_physical`

## Pressure and viscous split

| Force group | CD_total | CD_pressure | CD_viscous | Pressure share | Viscous share |
|---|---:|---:|---:|---:|---:|
| primary | 0.03320877 | 0.02289777 | 0.01031100 | 68.95% | 31.05% |
| total_physical | 0.03326556 | 0.02295001 | 0.01031555 | 69.00% | 31.00% |

The trailing-edge wall contribution is small but nonzero:

| Contribution | Delta CD |
|---|---:|
| `total_physical - primary` | 0.00005679 |
| pressure part | 0.00005225 |
| viscous part | 0.00000455 |

Do not use OpenFOAM `forceCoeffs` `Cd(f)` / `Cd(r)` as a pressure/viscous split. Those fields are front/rear coefficient components, not the decomposition used above. The pressure/viscous values above come from the `forces` integration summarized into `grid_family_results.csv`.

## CL comparison to old design point

| Quantity | Value |
|---|---:|
| Old AVL/design CL | 1.16853 |
| CFD Fine `CL_primary` | 1.160934 |
| Absolute CL delta | -0.007596 |
| Relative CL delta | -0.650% |

The CFD drag gap is not explained by a large lift mismatch. The accepted CFD reference is within about `0.7%` of the old design CL.

## Spanwise and upper/lower contribution status

The current accepted Fine artifacts do not include a spanwise force binning or separate `airfoil_upper` and `airfoil_lower` force-function-object output. Existing force objects aggregate `airfoil_upper airfoil_lower` for `primary`.

Available patch-level evidence:

| Patch/group evidence | Available? | Notes |
|---|---|---|
| pressure vs viscous drag | yes | In `grid_family_results.csv` |
| primary vs total_physical | yes | `primary` plus `te_wall` |
| upper/lower force split | no | Requires separate force objects or post-processing integration |
| spanwise drag split | no | Requires binning by span station or surface integration by spanwise zones |
| upper/lower yPlus split | yes | Upper mean `0.8338`; lower mean `0.7559` |

Engineering implication: lack of spanwise and upper/lower force split is a diagnostic gap. It does not invalidate the accepted total force by itself, but it prevents us from locating whether the high CFD drag is an inboard pressure/form feature, a tip/outboard effect, a wake/numerical effect, or a broad fully turbulent skin-friction increase.
