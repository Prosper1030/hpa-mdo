# CalculiX Parity Gate

## Purpose

CalculiX is the Mac-local structural cross-check solver for the Phase 14 beam benchmark ladder. It is intended to catch beam-deck bookkeeping and model-form problems early, without turning ANSYS/APDL into a daily execution dependency.

This route is a linear-static parity route first:

- use CalculiX beam decks for B1-B5
- compare internal beam references against external FEM on controlled cases
- treat APDL as the later external confirmation route, not the day-to-day gate

## What This Gate Is

- A local beam-element parity check for Phase 14 benchmark cases
- A solver-discovery path that respects repo config overlay via `load_config(...)`, `find_ccx(cfg)`, and `find_gmsh(cfg)`
- A report-first validation layer that writes benchmark decks, runs `ccx_2.23` when available, and summarizes internal-vs-FEM errors under `output/phase14_dual_beam_calibration/`

## What This Gate Is Not

- Not a replacement for the later ANSYS/APDL external check
- Not a nonlinear large-deflection route
- Not a STEP -> Gmsh shell-mesh validation route for B1-B5
- Not an implementation of ASWING, aeroelastic trim, flutter, or beam-wire nonlinear behavior
- Not permission to edit `dual_beam_production` physics equations, hard gates, or aerodynamic ranking

## Scope Rules

- Use linear static CalculiX only
- Do not enable `NLGEOM` in this parity gate
- Do not use `WIRE_MAIN_TRUSS` as the first wire benchmark mode
- First wire rung is the APDL-style vertical wire surrogate: main-wire-node `UZ = 0`
- If a wire node is also a rib-link node, the CalculiX deck may reverse the `*EQUATION` dependency on `UZ` to satisfy MPC hierarchy rules while preserving the same kinematic intent
- Rib transfer is rigid-link / equal-DOF parity first; finite-stiffness rib surrogates belong to a later rung

## Solver Policy

- CalculiX is the Mac-local, fast-turnaround structural cross-check solver
- ANSYS/APDL remains the final external check when a benchmark is mature enough to deserve it
- Gmsh / shell / solid routes remain separate higher-fidelity inspections; they are not the first-line truth source for B1-B5 beam parity

## ASWING Boundary

The ASWING manual and repo research notes are allowed as conceptual references only:

- large-deflection beam behavior
- flexible-joint ideas
- future beam-wire / aeroelastic direction
- coordinate-system caution

They are not part of this MVP implementation. No ASWING-like solver behavior should be added here.

## Current Phase 14 MVP Readout

Current Mac-local evidence from the CalculiX beam parity runner:

- B1 tip-load and uniform-load cantilevers pass closed-form and internal-vs-FEM checks. This validates the basic units, `E/I`, pipe-section syntax, load direction, root clamp, and local CalculiX execution path.
- B3 dual-beam lift-only parity passes the current 5% displacement target. This is the linear no-wire dual-beam baseline.
- B2 tapered cantilever remains a warning case. The `b2_taper_diagnosis` sweep and the round-4 solution hunt both show that the 10-12% gap is insensitive to mesh refinement and legal section-sampling variants, while like-for-like element-type swaps are rejected because `SECTION=PIPE` is restricted to `B32R`. Treat this as a stable tapered-section/B32R PIPE formulation mismatch until the APDL truth deck is checked.
- B4 vertical-wire now has trustworthy corrected reaction bookkeeping for the current APDL-style `UZ = 0` surrogate: the missing force was the rear linked wire-station node carried through the MPC, and the corrected root/wire reactions close equilibrium once constrained-node loads are added back. This does not make it a tension-only cable truth model; it makes it a defensible linear surrogate for this rung.
- B5 is no longer blocked by lack of a CalculiX torque observable. The round-4 solution hunt shows that `*EL FILE, SECTION FORCES` cleanly exposes direct `main_beam_my_about_main_spar` beam-axis torque ownership, while the `front_rear_vertical_couple` case still behaves like a separate bending/shear surrogate in this linked dual-beam topology. So B5 remains warning-level as one blended parity gate, but direct `MY` is now auditable through section forces.

## Phase 14 Mac-Local Shell Hardening Readout

Current hardening artifacts are under `output/phase14_dual_beam_calibration/maclocal_fem_hardening/`.

- Constant tube shell bending is stable but warning-grade, not a strict truth gate. The fine structured-S4 tip-load case gives `UZ = -0.911266 m` versus closed-form `-0.982509 m` (`7.251%` error); the fine uniform-load case gives `UZ = -0.346407 m` versus `-0.368441 m` (`5.980%` error).
- Constant tube shell torsion is also warning-grade. The fine structured-S4 ring-torque case gives `theta = 0.0434057 rad` versus `T L / GJ = 0.0467920 rad` (`7.237%` error), with tight mesh movement but a persistent stiffness bias.
- B5 shell torsion is improved but still diagnostic: the legacy Gmsh triangular shell route remains bad at about `76.849%` theta error, while the structured-S4 end-ring tangential route is about `7.237%` error on the fine mesh.
- B2 tapered shell is now useful as a bounded diagnostic. The structured-S4 root-ring/tributary-load fine mesh gives `tip UZ = -0.171790 m`, `4.424%` from the internal beam value and `7.069%` from the B32R PIPE value. This does not retire APDL because the constant tube shell ladder did not meet the strict 5% closed-form threshold.

Trust categories for this shell line:

- trusted daily gate: existing CalculiX beam parity and B5 direct-MY section-force torque ownership
- directional diagnostic: constant shell WARN rows, improved B5 structured-S4 shell torsion, and B2 structured-S4 tapered shell comparison
- not trustworthy yet: legacy Gmsh triangular B5 shell torsion and any shell value used without mesh/convergence context
- APDL-required: final B2 tapered truth, final B5 twist/GJ truth, and root-cap/reference-node coupling claims

## Phase 14 FEM Fidelity Ladder Decision

The current fidelity-ladder workflow writes its decision matrix under
`output/phase14_dual_beam_calibration/maclocal_fem_fidelity_ladder/`.
The key engineering update is that the structured shell stiffness bias was not
primarily a material or solver calibration issue. It came from using the tube
outer radius as the shell reference surface. With the shell mesh placed at the
tube mid-surface radius, the constant tube checks become agreement-quality:

- tip-load bending: `0.062%` error on the fine S4 mesh
- uniform-load bending: `0.569%` error on the fine S4 mesh
- tip-torque torsion: `0.070%` error on the fine S4 mesh

That makes the corrected structured S4 shell route the best current Mac-local
thin-wall diagnostic route. It is still validation tooling: do not use it to
change aerodynamic ranking, hard gates, `dual_beam_production` physics, or add
calibration factors.

The 3D solid/volume probe is not promoted. The C3D8R structured-hex route runs
and closes reactions, but it is far too stiff for this slender thin-wall tube at
Mac-safe mesh sizes. Even the axial-refined `192 x 32 x 2` case remains about
`65.6%` off in constant tip-load bending and about `83.0%` off in torsion. Treat
that as a useful failed route, not as higher-fidelity truth.

Current route roles:

- daily gate: internal equivalent/tubing beam plus CalculiX B32R PIPE beam parity
- design diagnostic: corrected mid-surface structured S4 shell
- not recommended: current Mac-safe C3D8R solid tube probe and legacy triangular shell
- APDL-required: final B2 tapered truth and final B5 twist/GJ truth

The best-route B2/B5 rerun uses the same corrected mid-surface S4 convention:

- B2 tapered tube: `tip UZ = -0.184074 m`, which is `2.410%` from the
  internal tubing beam (`-0.179741 m`) and `14.725%` from the B32R PIPE
  reference (`-0.160448 m`). This supports the internal tubing model as a
  Mac-local diagnostic but leaves the B32R/APDL tapered-section question open.
- B5 single-tube torsion: `theta = 0.0468246 rad` versus closed-form
  `0.0467920 rad`, or `0.070%` error.
- Next APDL action: run `run_all_phase14.mac`; the key decks are
  `phase14_b2_tapered_tube.mac` and `phase14_b5_single_torsion.mac`.

## Practical Use

Run:

```bash
./.venv/bin/python -m pytest tests/test_hifi_calculix_runner.py tests/test_phase14_calculix_solution_hunt.py tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
./.venv/bin/python scripts/phase14_maclocal_fem_package.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration --task hardening
./.venv/bin/python scripts/phase14_calculix_beam_benchmarks.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration/round4_benchmarks
./.venv/bin/python scripts/phase14_calculix_solution_hunt.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration --task b2
./.venv/bin/python scripts/phase14_calculix_solution_hunt.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration --task b5
```

Expected artifacts:

- `output/phase14_dual_beam_calibration/round4_benchmarks/*.inp`
- `output/phase14_dual_beam_calibration/round4_benchmarks/*.frd`
- `output/phase14_dual_beam_calibration/round4_benchmarks/*.dat`
- `output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv`
- `output/phase14_dual_beam_calibration/comparison_summary.md`
- `output/phase14_dual_beam_calibration/b2_taper_diagnosis.csv`
- `output/phase14_dual_beam_calibration/b2_taper_diagnosis.md`
- `output/phase14_dual_beam_calibration/b2_solution_hunt.csv`
- `output/phase14_dual_beam_calibration/b2_solution_hunt.md`
- `output/phase14_dual_beam_calibration/b4_wire_reaction_diagnosis.csv`
- `output/phase14_dual_beam_calibration/b4_wire_reaction_diagnosis.md`
- `output/phase14_dual_beam_calibration/b5_torque_parity_diagnosis.csv`
- `output/phase14_dual_beam_calibration/b5_torque_parity_diagnosis.md`
- `output/phase14_dual_beam_calibration/b5_single_beam_torsion_probe.csv`
- `output/phase14_dual_beam_calibration/b5_single_beam_torsion_probe.md`
- `output/phase14_dual_beam_calibration/b5_solution_hunt.csv`
- `output/phase14_dual_beam_calibration/b5_solution_hunt.md`
- `output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_bending.csv`
- `output/phase14_dual_beam_calibration/maclocal_fem_hardening/constant_tube_torsion.csv`
- `output/phase14_dual_beam_calibration/maclocal_fem_hardening/b5_shell_torsion_hardening.csv`
- `output/phase14_dual_beam_calibration/maclocal_fem_hardening/b2_tapered_shell_hardening.csv`
- `output/phase14_dual_beam_calibration/maclocal_fem_hardening/overnight_summary.md`
- `output/phase14_dual_beam_calibration/apdl_truth_decks/*.apdl`
- `output/phase14_dual_beam_calibration/round4_solution_hunt_summary.md`

## Engineering Interpretation

- Passing B1 means the local CalculiX beam deck, units, section syntax, and cantilever bookkeeping are sane
- Passing B3 means the explicit front/rear beam split plus rigid-link parity deck is directionally credible
- B2 should remain a warning case until the tapered-beam APDL truth deck says otherwise; the current Mac-local evidence does not support hiding the 10-12% CalculiX stiffness bias with tolerances or deck tricks
- B4 displacement parity is useful, and corrected root/wire reactions are now engineering-meaningful for the APDL-style vertical-wire surrogate. The trust boundary is the surrogate itself, not the bookkeeping any more.
- B5 is not validated by `UZ` parity alone. Use `SECTION FORCES` for direct `MY` torque ownership, and keep the front/rear force-couple route in a separate surrogate bucket unless APDL later proves it is an acceptable truth-equivalent replacement.
- `NLGEOM` remains deferred until the linear parity route is cleaner
- `WIRE_MAIN_TRUSS` is still not the first parity target; the first wire rung remains the APDL-style vertical `UZ = 0` surrogate
- CalculiX is the Mac-local daily cross-check, while ANSYS/APDL remains the final external structural check
- ASWING remains conceptual future reference only; do not back-port ASWING-like nonlinear behavior into this gate
- Do not use this route to justify production calibration factors or to silently reweight hard constraints
