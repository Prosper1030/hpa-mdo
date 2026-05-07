# Recommended Fix Or Next Test

1. Add an explicit decomposed moment-closure API that reports Mx, My, Mz separately plus applied, root, wire, and link contributions.
2. Treat current all-axis `moment_closure_passed` as diagnostic/report-only until the yaw/offset-link generalized-force convention is made self-consistent.
3. For aerodynamic Cm, run a targeted A/B using the same model with torque as `main_beam_my_about_main_spar` versus an explicit front/rear vertical couple about the main spar.
4. If the vertical-couple path closes while main-beam My does not, patch production torque ownership before FEM.
5. Run external FEM only after the moment ownership path is chosen; use the 16.030 kg `4a5b3187fd18` recipe for a smoke check, not the old 77 kg branch.

Do not use this moment-closure failure alone to reject the 6-7 deg z state yet. It is a structural-model validation blocker, not a final spar sizing result.
