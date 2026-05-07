# External FEM Route Assessment

## Availability Summary

### Config state in `configs/blackcat_004.yaml`

- `hi_fidelity.gmsh.enabled: false`
- `hi_fidelity.gmsh.binary: null`
- `hi_fidelity.calculix.enabled: false`
- `hi_fidelity.calculix.ccx_binary: null`

### Local machine check from this task

- `gmsh` on `PATH`: yes, `/opt/homebrew/bin/gmsh`
- `ccx` on `PATH`: not found

### Important code-path consequence

- `src/hpa_mdo/hifi/gmsh_runner.py:find_gmsh()` returns `None` when the config flag is off, even if a system `gmsh` binary exists.
- `src/hpa_mdo/hifi/calculix_runner.py:find_ccx()` returns `None` when the config flag is off, and in this checkout `ccx` is also absent from `PATH`.

Engineering meaning:

- Gmsh is physically installed on this machine, but the current project config disables it.
- CalculiX is effectively unavailable to the current config and also not discoverable on `PATH`.
- So the existing high-fidelity driver is present in code, but not “ready to run today” under the default config.

## Existing External-Comparison Routes

## 1. ANSYS equivalent-beam export

- Main files:
  - `src/hpa_mdo/structure/ansys_export.py`
  - `scripts/ansys_crossval.py`
  - `scripts/ansys_compare_results.py`
  - `docs/ansys_equivalent_beam_validation_pass.md`
- Best use:
  - clean apples-to-apples beam validation of the legacy equivalent-beam assumptions
- Current assessment:
  - strongest already-validated external beam route in the repo
  - useful as Benchmark 1 and Benchmark 2 infrastructure

## 2. ANSYS dual-spar spot-check

- Main files:
  - `scripts/ansys_dual_spar_spotcheck.py`
  - `docs/dual_spar_spotcheck_workflow.md`
  - `output/_archive_pre_2026_04_15/blackcat_004_internal_dual_beam_smoke_with_ansys/dual_beam_internal_report.txt`
- Best use:
  - apples-to-apples explicit two-beam parity check
  - spot-checking model-form risk relative to the equivalent-beam route
- Current assessment:
  - closest existing route to a controlled two-beam external benchmark
  - should be reused for Benchmark 3 before any shell-mesh route

## 3. ANSYS dual-beam production export

- Main files:
  - `scripts/ansys_dual_beam_production_check.py`
  - `src/hpa_mdo/structure/ansys_export.py`
  - `output/_archive_pre_2026_04_15/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
  - `output/_archive_pre_2026_04_15/blackcat_004_dual_beam_production_check/production_vs_dual_spar_ansys_surrogate.txt`
- Best use:
  - inspection route toward production-like external comparison
- Current assessment:
  - promising, but not yet calibration-grade
  - the repo currently contains a contract ambiguity that must be resolved before this route is trusted:
    - `dual_beam_mainline/types.py` and `tests/test_dual_beam_mainline.py` freeze production aerodynamic torque as `main_beam_my_about_main_spar`
    - `ansys_export.py` production APDL load writer emits nodal `FZ` lines only
    - comments and report text still mention aerodynamic torque couples in places
- Engineering judgment:
  - Round 2 must audit this production torque contract before Benchmark 5
  - do not assume the archived production APDL deck is already apples-to-apples with the current internal torque channel

## 4. Gmsh -> CalculiX structural check

- Main files:
  - `src/hpa_mdo/hifi/gmsh_runner.py`
  - `src/hpa_mdo/hifi/calculix_runner.py`
  - `src/hpa_mdo/hifi/structural_check.py`
  - `scripts/hifi_structural_check.py`
  - `scripts/export_dual_beam_step.py`
- Best use:
  - local structural spot-check
  - mesh, support, load-replay, and compare-contract diagnosis
- Current assessment:
  - not the closest route to apples-to-apples beam validation
  - current best evidence run is still `shell_plus_beam`, `has_volume_elements = false`, `overall_comparability = LIMITED`
  - best recent numbers are encouraging for support reaction and reasonable for tip deflection:
    - support reaction diff about `0.00284%`
    - tip deflection diff about `6.72%`
  - that is good spot-check evidence, not finished beam calibration truth

## Which Route Is Closest To Apples-To-Apples Beam Validation?

Closest today, in order:

1. `equivalent_beam` ANSYS parity route for single-beam benchmarks
2. `dual_spar` ANSYS parity route for explicit two-beam benchmarks
3. a future audited `dual_beam_production` beam deck after torque ownership is frozen
4. only after the above, the Gmsh -> CalculiX shell-plus-beam route

## Which Route Is Only A Shell / Mesh Spot-Check?

The current `STEP -> Gmsh -> CalculiX -> structural_check` line is a shell / mesh spot-check route.

It should not be treated as final truth because:

- it is not yet a beam-only benchmark,
- it still depends on mesh healing and support-patch heuristics,
- it currently has no volume elements in the representative compare run,
- and its load contract is strongest for distributed `Fz`, not for the full torque and composite problem.

## Should Round 2 Use Beam-Element Decks Before STEP / Gmsh Shell Mesh?

Yes.

This is the clearest engineering recommendation in this report.

Why:

- Beam benchmarks isolate section properties, BCs, wire, and torque ownership cleanly.
- The current shell route adds too many extra moving parts:
  - STEP quality
  - Gmsh healing
  - shell normals
  - shell duplication
  - support clustering
  - no-volume-element outcomes
- If Benchmark 3 or 4 fails in a shell route first, the failure is too ambiguous to calibrate safely.

So Round 2 should:

1. freeze beam benchmarks 1 to 5,
2. export and compare beam decks first,
3. use the existing shell-plus-beam CalculiX path only after the lower-rung beam cases are interpretable.

## Exact Files And Functions Future Implementation Should Inspect Or Call

### Internal model and load-contract builders

- `src/hpa_mdo/structure/dual_beam_mainline/builder.py:build_dual_beam_mainline_model`
- `src/hpa_mdo/structure/dual_beam_mainline/load_split.py:build_dual_beam_load_split`
- `src/hpa_mdo/structure/dual_beam_mainline/api.py:run_dual_beam_mainline_analysis`
- `src/hpa_mdo/structure/dual_beam_mainline/types.py:get_analysis_mode_definition`

### Existing ANSYS deck generation

- `src/hpa_mdo/structure/ansys_export.py:ANSYSExporter`
- `src/hpa_mdo/structure/ansys_export.py:write_apdl`
- `src/hpa_mdo/structure/ansys_export.py:write_workbench_csv`
- `src/hpa_mdo/structure/ansys_export.py:write_nastran_bdf`
- `scripts/ansys_crossval.py`
- `scripts/ansys_dual_spar_spotcheck.py`
- `scripts/ansys_dual_beam_production_check.py`
- `scripts/ansys_compare_results.py`

### Existing CalculiX and Gmsh helpers

- `src/hpa_mdo/hifi/gmsh_runner.py:find_gmsh`
- `src/hpa_mdo/hifi/gmsh_runner.py:mesh_step_to_inp`
- `src/hpa_mdo/hifi/gmsh_runner.py:collect_mesh_diagnostics`
- `src/hpa_mdo/hifi/calculix_runner.py:find_ccx`
- `src/hpa_mdo/hifi/calculix_runner.py:prepare_static_inp`
- `src/hpa_mdo/hifi/calculix_runner.py:prepare_buckle_inp`
- `src/hpa_mdo/hifi/calculix_runner.py:run_static`
- `src/hpa_mdo/hifi/structural_check.py:run_structural_check`

### Existing compare-contract helper worth reusing

- `scripts/validate_benchmark_contract.py`

This script already understands the structure of a frozen benchmark compare:

- AI-side metrics JSON
- CalculiX `.inp` / `.dat` / `.frd`
- mass, reaction, deflection, and optional twist comparison

It is a good starting point for Round 2 comparison plumbing.

## Assessment Conclusion

- The repo already has enough export and compare plumbing to start Round 2.
- The right first move is not shell mesh hardening. It is a controlled beam-benchmark export ladder.
- The one route that looks closest to current production truth, the production APDL export, still needs a torque-contract audit before calibration work should trust it.
