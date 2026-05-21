# Coarse Extended Solver Report

Verdict: `coarse_not_converged_by_requested_force_window_gate`

- case: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/coarse_extended_current_setup/openfoam_cases/coarse/fullwing_artificial_tip_symmetry`
- last primary row: Time `1000.0`, CD `0.04178047`, CL `1.074658`, CmPitch `-0.1237927`
- last total_physical row: CD `0.0419035`, CL `1.074643`, CmPitch `-0.1236824`
- simpleFoam first segment: `{'returncode': 0, 'timed_out': False, 'stopped_by_runaway_guard': False, 'runaway_time': None, 'elapsed_s': 1942.266504375264}`
- simpleFoam extension segment: `{'returncode': 0, 'timed_out': False, 'stopped_by_runaway_guard': False, 'runaway_time': None, 'elapsed_s': 1881.1113154171035}`
- yPlus status: `available`

## Stability

- final-100 at 500, primary: `{"Cd": {"last": 0.05266464, "rel_span": 0.05208970809792425}, "Cl": {"last": 0.9571043, "rel_span": 0.032971190407772306}, "CmPitch": {"last": -0.111228, "rel_span": 0.03330662400460389}}`
- final-100 at 500, total_physical: `{"Cd": {"last": 0.05285709, "rel_span": 0.052193908693101275}, "Cl": {"last": 0.9570817, "rel_span": 0.0329734949810469}, "CmPitch": {"last": -0.1110586, "rel_span": 0.0335387565773962}}`
- accepted at 500 by requested gate: `False`
- final-100 at final time, primary: `{"Cd": {"last": 0.04178047, "rel_span": 0.04031947759900397}, "Cl": {"last": 1.074658, "rel_span": 0.016559984705489608}, "CmPitch": {"last": -0.1237927, "rel_span": 0.013260732496327084}}`
- final-100 at final time, total_physical: `{"Cd": {"last": 0.0419035, "rel_span": 0.04048220862957815}, "Cl": {"last": 1.074643, "rel_span": 0.01656211163349173}, "CmPitch": {"last": -0.1236824, "rel_span": 0.013334877066218267}}`
- accepted at final time by requested gate: `False`

## Reference Equivalence

- user-supplied acceptance target: `CL_primary=1.130726`, `CD_total_physical=0.031823`
- repo-traceable stored reference: `CL_primary=1.133291`, `CD_primary=0.03276165`, `CD_total_physical=0.0327769065`
- CL error vs user target: `-0.04958584130903509`
- CD_total_physical error vs user target: `0.3167677465983725`
- CL error vs repo-stored reference: `-0.05173693252659745`
- CD_primary error vs repo-stored reference: `0.2752858906678997`
- CD_total_physical error vs repo-stored reference: `0.278445847230885`
- accepted reference reproduction: `False`

Medium/Fine remain gated until this report says the Coarse run is stable
and reference-equivalent.
