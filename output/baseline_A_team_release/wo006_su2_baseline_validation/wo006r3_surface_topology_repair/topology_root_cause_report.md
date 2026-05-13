# WO-006R3 Surface Topology Repair Report

Verdict: `wo006r3_high_mesh_handoff_ready`

## Authority Basis

- Mass authority: `98.5 kg`.
- Span authority: `34.332286 m` full / `17.166143 m` half.
- References: Sref `33.420059598 m^2`, Cref `1.003721543 m`, Bref `34.332286 m`.
- Source geometry authority stayed fixed: `current_avl_compromise_conservative_closed`.
- `106.828608 kg` remained a suspect screening aggregate; `16.5 m` remained a blocked local/splice screening reference.

## Plain-Language Root Cause

WO-006R2 was not primarily a solver problem. The current GO mesh-native adapter was feeding Gmsh a faceted wing boundary whose DAE31 airfoil loop could locally fold near the trailing edge, so Gmsh saw physically impossible segment/facet intersections before a serious mesh could reach SU2. The exact old blockers at y about `12.54-12.59 m` and `7.47 m` disappeared after repairing the DAE31 near-TE branch ordering, which confirms the old symptoms were surface-topology symptoms rather than mass/span/reference issues.

After that repair, the BL route still exposes DAE31-family PLC blockers at y about `3.66 m` and `10.69 m`. So the current state is: the general current-GO no-BL surface can be high-meshed and read by SU2, but the Gmsh topological BL extrusion path still needs a dedicated surface/curve-ownership repair before it is a viscous CFD handoff.

## Old Evidence Reused

- Old `wing_h=0.20 m` HXT BL mesh: `1,125,409` cells, reused as the serious BL target/template, not as current coefficient evidence.
- Old `wing_h=0.15 m` HXT BL failure: `1,515,251` cells, reused as the warning boundary for BL quality/topology.
- Old no-BL solver evidence was used only as route-readability context, not as current Baseline A drag truth.

## Repair Attempts

See `repair_attempts_summary.csv` for the full accepted/rejected table.

Key accepted repairs:

- DAE31 near-TE branch ordering repair in the mesh-native resampler.
- Same-station airfoil-loop intersection preflight.
- Shorter panel diagonalization for no-BL faceted SU2 handoff only.

Key rejected or bounded repairs:

- Applying shorter diagonalization blindly to BL extrusion produced `Unknown curve -1550`; it is rejected for BL until the BL curve/surface ownership path is repaired.
- Coarsening BL from `wing_h=0.20 m` to `0.25 m` did not remove the remaining PLC blocker.

## Handoff Status

`mesh_handoff.v1.json` records the accepted handoff:

- Handoff kind: current-GO high-mesh no-BL SU2 readability handoff.
- Mesh: `936017` volume cells, `176542` nodes.
- Mesh gate: `pass` with warnings `very_low_min_gamma`.
- Marker audit: `pass`.
- SU2 readability smoke: `timeout`, reached iteration `75` before the 90 s timeout.
- CFD evidence gate: `fail`.

The serious BL handoff does **not** materialize. The high-mesh no-BL handoff does materialize and is SU2-readable, but it is not a viscous drag/calibration case.

## Coefficients

No SU2 coefficient is interpretable for Baseline A. The 90 s readability smoke produced positive sign-sanity coefficients, but the CFD evidence gate failed because it reached only `75` iterations, there is no convergence gate pass, and there is no BL/y+ evidence.

Baseline A reopen status: `not_evaluated`.

## Verification

- Final policy campaign: `scripts/run_wo006r2_cfd_recovery_campaign.py --skip-solver --mesh-timeout-seconds 360 --solver-timeout-seconds 1 --output-dir output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/final_policy_campaign`.
- High-mesh no-BL probe: `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/high_mesh_no_bl_wing_h_0p12_probe`.
- SU2 readability smoke summary: `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/high_mesh_no_bl_wing_h_0p12_probe/solver_readability_smoke_summary.json`.
- `PYTHONPATH=src:hpa_meshing_package/src ./.venv/bin/python -m pytest hpa_meshing_package/tests/test_mesh_native_blackcat.py hpa_meshing_package/tests/test_mesh_native_gmsh_polyhedral.py tests/test_wo006r2_cfd_recovery_campaign.py`: pass, 47 tests.
- `PYTHONPATH=src ./.venv/bin/python scripts/check_baseline_a_data_authority.py --check-only`: pass.
- `PYTHONPATH=src:hpa_meshing_package/src ./.venv/bin/python -m ruff check hpa_meshing_package/src/hpa_meshing/mesh_native/blackcat.py hpa_meshing_package/src/hpa_meshing/mesh_native/gmsh_polyhedral.py hpa_meshing_package/src/hpa_meshing/mesh_native/wing_surface.py hpa_meshing_package/tests/test_mesh_native_blackcat.py hpa_meshing_package/tests/test_mesh_native_gmsh_polyhedral.py tests/test_wo006r2_cfd_recovery_campaign.py`: pass.
- `git diff --check`: pass.

## Engineering Caveats

- This is CFD route recovery, not aerodynamic validation.
- No-BL tetra meshes cannot support profile-drag or low-Re transition claims for this HPA wing.
- The DAE31 adapter canonicalization repairs a nonphysical loop crossing in generated mesh-native surface data; it does not alter authority source files, but it still needs reviewer scrutiny before being called exact external-shape preservation.
- The remaining BL blocker is now more precise: DAE31-family surface topology / Gmsh BL curve ownership, not data authority or old CST-tip transition evidence.
- A future BL fix must not change mass, CG, span, Sref/Cref/Bref, spar/RFQ, or procurement truth.

## Reviewer Prompt

```text
Review output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/ as CFD geometry-adapter reviewer. Check topology_root_cause_report.md, plc_intersection_localization.csv, repair_attempts_summary.csv, blocker_register.csv, mesh_handoff.v1.json, final_policy_campaign/, and high_mesh_no_bl_wing_h_0p12_probe/. Decide whether wo006r3_high_mesh_handoff_ready is supported without overstating BL readiness, external-shape preservation, SU2 coefficient interpretability, Baseline A reopen status, RFQ/procurement truth, or final aircraft sign-off.
```
