# Output Channel Authority

Generated `output/` artifacts are evidence, not Baseline A authority, unless
`output/baseline_A_team_release/data_authority_table.csv` explicitly allows the
number or verdict for the intended use.

Current Baseline A repair rules:

- `output/baseline_A_team_release/` is a generated evidence package under data-authority repair.
- `output/current_pathfinder*/` is current-pathfinder evidence only.
- `output/go_mode_main_wing_candidate/final_candidate_package/` is pipeline evidence only.
- `output/phase*` is legacy/experiment evidence unless `CURRENT_MAINLINE.md` promotes a specific artifact.
- WO-005 RFQ outputs are draft/vendor-screening only.
- WO-006 SU2 remains paused until data authority is restored.

Do not promote `106.828608 kg`, `16.5 m`, or `-9 W` from generated output into
README, CURRENT_MAINLINE, release claims, procurement decisions, or Baseline A
reopen decisions without the authority table and a reconciliation report.
