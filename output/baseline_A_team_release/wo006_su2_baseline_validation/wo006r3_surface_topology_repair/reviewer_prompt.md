Review output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/ as CFD geometry-adapter reviewer.

Return pass / needs_fix / dangerous_assumption / reopen_risk.

Check:
- Is `wo006r3_high_mesh_handoff_ready` supported by `mesh_handoff.v1.json`, the 0.12 no-BL high-mesh probe, marker audit, and SU2 readability smoke?
- Does the report avoid claiming BL handoff readiness? BL still fails at DAE31-family PLC points in `final_policy_campaign/blocker_register.csv`.
- Does it keep 98.5 kg, 34.332286 m / 17.166143 m, Sref/Cref/Bref, mass/CG, spar/RFQ, and procurement authority fixed?
- Does it explicitly say coefficients are not interpretable because the CFD evidence gate fails and no BL/y+ evidence exists?
- Is the DAE31 near-TE canonicalization described as adapter-level topology repair, not a certified external-shape change?
- Are old Black Cat / old BL / no-BL coefficients kept as route evidence only, not current Baseline A truth?
