# Z-State Structure-Budget Sweep Summary

This MVP holds the smooth_tier2_production_baseline geometry and AVL spanwise lift ownership fixed, then sweeps requested loaded beam-line Z through the canonical `scripts/direct_dual_beam_inverse_design.py` entrypoint.

## Contract

- spar/tube mass target: 11.500 kg
- canonical total-structural mass cap passed to direct route: 14.000 kg
- non-tube structural allowance used for that cap: 2.500 kg
- healthy jig clearance threshold: 20.0 mm
- refresh_steps: 0
- aero source: candidate_avl_spanwise from smooth production AVL strip-force artifact
- Stage 1 bridge authority: AVL actual spanload, not raw commanded Fourier coefficients
- ranking / hard gates: unchanged

## Stage 1 Bridge Trace

- calibration artifacts available: True
- calibration case count: 10
- bridge status counts: {"outer_underloaded_authority_limited": 10}
- recommended bridge report: /Volumes/Samsung SSD/hpa-mdo/output/pipeline_redesign_v2/fourier_avl_calibration_mvp/recommended_fourier_bridge.md

## Results

- first sampled mass pass: 4.250 m, 13.906 deg, tube 9.689 kg, clearance 44.4 mm
- first sampled feasible contract pass: 4.250 m, 13.906 deg, tube 9.689 kg, clearance 44.4 mm
- old x4-equivalent check: 4.250 m, 13.906 deg, tube 9.689 kg, clearance 44.4 mm

## Explicit Answers

1. Total effective cruise dihedral corresponds to the loaded aerodynamic surface tip Z relative to the aerodynamic root reference. In this MVP, `effective_dihedral_deg` in the sweep CSV uses beam-line `target_main_tip_z_m / semi_span` as a proxy because canonical inverse design is driven by spar beam-line targets.
2. 5-7 deg sampled states meet the 11.5 kg tube target: no. They meet the full MVP budget including healthy clearance: no.
3. At the sampled 6 deg target, the required selected tube mass is 14.703 kg under this canonical MVP sweep.
4. The lowest sampled state meeting tube mass with healthy clearance is 4.250 m / 13.906 deg.
5. The previous 2.675-2.70 m points were not both sampled.
6. Send 4.250 m first to AVL loaded-shape recheck; also keep the nearest lower non-healthy/mass-boundary point and old x4-equivalent row as sensitivity checks.

## Engineering Read

- The current smooth aero geometry by itself is only about 3.5 deg effective dihedral by the exported section-table z; the low-mass structural states found here require much higher beam-line target Z.
- That mismatch is an engineering warning, not a software failure: before finalizing the production state we need an explicit aero-surface-to-beam-line offset contract and an AVL recheck of the realizable loaded shape.

## 5-7 Deg Blockers

- target_main_tip_z_1p804m: blockers=canonical_total_mass_cap, ground_clearance, tube_spar_mass_budget, tube=14.703 kg, total=17.203 kg, clearance=-193.7 mm
- target_main_tip_z_2p108m: blockers=canonical_total_mass_cap, ground_clearance, tube_spar_mass_budget, tube=13.982 kg, total=16.482 kg, clearance=-136.7 mm
