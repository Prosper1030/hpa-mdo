# Original Baseline A Drag/Power Source Report

## Scope

This audit traces the original Baseline A `CD_total≈0.02602` and
`P_crank≈174 W` without running new CFD. It follows the exact generated source,
the script formula, and the later release-package propagation.

## Exact Computational Source

The exact source that produced `174.60027944116567 W` is
`scripts/tier2_loaded_shape_airfoil_mvp.py`.

Key evidence:

- `scripts/tier2_loaded_shape_airfoil_mvp.py:63-64` fixes
  `ETA_PROP = 0.88` and `ETA_TRANS = 0.96`.
- `scripts/tier2_loaded_shape_airfoil_mvp.py:68-79` defines the mission
  contract and sets `CDA_nonwing_target_m2 = 0.13`.
- `scripts/tier2_loaded_shape_airfoil_mvp.py:694-708` forms
  `CD_total = CDi + profile.cd0_total_est`, writes nominal `P_crank`, and writes
  `P_crank_conservative` with `1.05 * CDi + CD0_total`.
- `scripts/tier2_loaded_shape_airfoil_mvp.py:777-782` converts drag to crank
  power with `q = 0.5 * rho * V^2` and
  `P_crank = q * S * CD_total * V / (ETA_PROP * ETA_TRANS)`.
- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_selected_avl_recheck.csv:3`
  is the exact generated row:
  `CL=1.16853`, `CDi=0.0127613`, `profile_cd=0.009368851143241826`,
  `CD0_total=0.013258730502038055`, `CD_total=0.026020030502038057`,
  `P_crank=174.60027944116567`, and
  `P_crank_conservative=178.8818396527458`.

## Inputs Used By That Row

The same generated bundle records the operating-point inputs:

- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_loaded_shape_avl_recheck/loaded_shape_local_cl_re_envelope.csv:2`
  shows `velocity_mps=6.6`, `density_kgpm3=1.18`,
  `dynamic_viscosity_pa_s=1.7228e-05`, and `aoa_deg=0.18015`.
- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/runs/conservative_best/conservative_best_loaded_shape_airfoils.avl:6-8`
  gives `Sref=33.420059598 m^2`, `Cref=1.003721543 m`,
  `Bref=34.332286000 m`.

## Release-Package Propagation

The same nominal `174.60027944116567 W` then propagates into later generated
artifacts:

- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_airfoil_assignment.json:7-13`
- `output/go_mode_main_wing_candidate/final_candidate_package/candidate_summary.csv:2`
- `output/go_mode_main_wing_candidate/final_candidate_package/GO_MODE_DECISION.md:28-35`
- `output/baseline_A_team_release/wo006_su2_baseline_validation/aero_model_delta_table.csv:4`

The later team-release freeze audit re-labels this value as
`Pre-tail main-wing P_crank`:

- `output/baseline_A_team_release/design_space_freeze_audit/design_space_freeze_audit.md:38-40`

That same freeze audit also shows a later separate tail placeholder charge:

- `output/baseline_A_team_release/design_space_freeze_audit/design_space_freeze_audit.md:39-40`
- `output/baseline_A_team_release/margin_budget.md:45-47`

So the original `174.6 W` is not a full release-grade aircraft total. It is a
pre-tail main-wing screening closure that was later combined with other
screening placeholders in downstream release packaging.

## Engineering Read

`174.6 W` is traceable and internally consistent as a generated screening
number, but its trust boundary is limited:

- It is built from AVL induced drag plus Tier2/XFOIL-derived wing profile drag
  plus a lumped non-wing reserve.
- It is not a CFD-calibrated aircraft drag truth.
- It is not a propulsion-validated truth; propeller and drivetrain losses are
  only represented through fixed efficiencies.
- It is not a final whole-aircraft sign-off number because the later release
  ledger still carries separate tail and mass-screening placeholders.
