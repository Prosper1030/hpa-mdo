# hpa-meshing-package

`hpa_meshing_package` 是 `hpa-mdo` 內正式追蹤的 meshing product root，目標是把已經跑通的 provider-aware meshing + package-native SU2 baseline 能力收斂成一個可交付、可維護、可繼續擴展的 Python package。

這個 package 目前代表的正式主線是：

```text
.vsp3
  -> openvsp_surface_intersection
  -> normalized trimmed STEP
  -> geometry-family-first dispatch
  -> gmsh_thin_sheet_aircraft_assembly
  -> mesh_handoff.v1
  -> su2_handoff.v1
  -> history / CL / CD / CM
  -> convergence_gate.v1
```

它不是最終高品質 CFD framework，也不是 `origin-su2-high-quality` 那條 case-specific workflow 的包裝版。

## Read This First

1. `README.md`
2. [`docs/current_status.md`](docs/current_status.md)
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
4. Contract docs in [`docs/contracts/`](docs/contracts)
5. High-fidelity route decision: [`../docs/research/high_fidelity_route_decision_2026-04-30.md`](../docs/research/high_fidelity_route_decision_2026-04-30.md)

## Official v1 Scope

### Works now

- `openvsp_surface_intersection` 是正式 `v1` geometry provider。
- 正式可執行的 meshing route 是 `aircraft_assembly` / `thin_sheet_aircraft_assembly`。
- Gmsh backend 會真的產生外流場 volume mesh，並輸出 `mesh_handoff.v1`。
- package-native SU2 baseline 會真的 materialize case、跑 `SU2_CFD`、parse history、輸出 `su2_handoff.v1`。
- reference provenance gate 和 force-surface provenance gate 已經接進 baseline SU2 handoff。
- mesh / iterative convergence gate 會直接寫進 `su2_handoff.v1` 與 `report.json`，明確標示這次 baseline run 是 `preliminary_compare`、`run_only` 還是 `not_comparable`。
- package-native mesh study 會用 `coarse / medium / fine` 預設，連跑同一幾何的 baseline CFD，並輸出 `mesh_study.v1`。

### Not in v1

- alpha sweep
- component-level force mapping
- final high-quality credibility claim
- ESP/OpenCSM runtime hard dependency

## Experimental / Placeholder Areas

- `esp_rebuilt` 目前已經能在本機 materialize provider-normalized geometry，但仍停留在 experimental：它不是 formal `v1` route；main-wing 已經能用 coarse bounded sizing 寫出 real `mesh_handoff.v1`，但這仍不是 production default mesh。
- `main_wing` / `tail_wing` / `fairing_solid` / `fairing_vented` 的 schema、family dispatch、route registry 已經存在；`main_wing` 已有 real ESP/VSP geometry、real Gmsh mesh handoff、real SU2 handoff、solver executed but not converged artifact，以及 reference-geometry warn gate；`tail_wing` 已有 real geometry / surface / blocker probes，`fairing_solid` 已有 real VSP geometry smoke、bounded real mesh handoff probe、real SU2 handoff materialization probe 與 external reference override handoff，但都還不是正式可交付 CFD 路徑。
- 目前只有 `gmsh_thin_sheet_aircraft_assembly` 會走真實 Gmsh meshing；其他 route 會回 `route_stage=placeholder`。
- `shell_v4` 是 BL / solver-entry diagnostic branch，不是任意主翼 product route；BL route 只有在 hpa-mdo owns transition sleeve / receiver faces / interface loops / layer-drop events 之後才可 promotion。

## ESP Reality Check

- `esp_rebuilt` 在目前 `main` 上已經不再是 `not_materialized` stub。它現在會走 native OpenCSM lifting-surface rebuild：從 `.vsp3` 讀 wing/tail sections，生成 rule-loft `.csm`，再用 `serveCSM -batch` 輸出 normalized STEP 與 topology artifact。
- 這台 Mac mini M4（macOS 26.4.1 / arm64）目前可用的 runtime truth 是：`serveESP` / `serveCSM` 在 `PATH` 上、`ocsm` 仍缺席，但 batch 路徑可以直接用 `serveCSM`。所以 `detect_esp_runtime()` 會回 `available=true`、`batch_binary=serveCSM`，provider 已可執行。
- 2026-04-30 的 `main_wing_esp_rebuilt_geometry_smoke.v1` 已經把主翼單體 real geometry evidence 收進 committed report：它從 `blackcat_004_origin.vsp3` 選到 `Main Wing`，產生 normalized STEP，topology 為 `1 body / 32 surfaces / 1 volume`。
- 目前真正的 blocker 已經往後移：coarse bounded real mesh handoff 和 real SU2 handoff 都已經 materialize，`SU2_CFD` 也能執行並寫出 `history.csv`；但 12-iteration smoke 的 convergence gate 為 `fail/not_comparable`，且 main-wing reference chord / moment origin 仍未獨立認證。
- 結論：`esp_rebuilt` 現在是「provider runnable + route artifact exists, but not production CFD」。下一步不是再補 runtime 安裝，也不是宣稱 solver converged，而是先把 reference provenance 補齊，再做 bounded longer-iteration / numerics campaign。
- 實作規劃請看 [ESP Rebuilt Provider Enablement Implementation Plan](../docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md)。

## Quick Start

### 1. Run tests

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests -q
```

### 2. Validate provider-normalized geometry

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli validate-geometry \
  --component aircraft_assembly \
  --geometry ../data/blackcat_004_origin.vsp3 \
  --geometry-provider openvsp_surface_intersection \
  --out .tmp/runs/blackcat_004_validate
```

This validates the provider-aware path and writes `report.json` / `report.md` plus provider artifacts under `.tmp/runs/blackcat_004_validate/artifacts/providers/`.

### 3. Run baseline CFD from package root

The copy-paste config for the canonical smoke is:

- [`configs/aircraft_assembly.openvsp_baseline.yaml`](configs/aircraft_assembly.openvsp_baseline.yaml)

The default HPA flow condition is explicit in that YAML: `V=6.5 m/s`,
`rho=1.225 kg/m^3`, `T=288.15 K`, and `mu=1.7894e-5 Pa*s`. Operators should
adjust flow conditions through `su2.flow_conditions` rather than editing the
SU2 runtime file after materialization.

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli run \
  --config configs/aircraft_assembly.openvsp_baseline.yaml
```

This produces:

- `report.json`
- `report.md`
- `artifacts/providers/openvsp_surface_intersection/normalized.stp`
- `artifacts/mesh/mesh_metadata.json`
- `artifacts/mesh/marker_summary.json`
- `artifacts/su2/alpha_0_baseline/su2_handoff.json`
- `artifacts/su2/alpha_0_baseline/history.csv`

### 4. Run the minimal baseline mesh study

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli mesh-study \
  --config configs/aircraft_assembly.openvsp_baseline.yaml \
  --out .tmp/runs/blackcat_004_mesh_study
```

This produces:

- `report.json` with the `mesh_study.v1` payload
- `cases/coarse/report.json`
- `cases/medium/report.json`
- `cases/fine/report.json`

### 5. Write the component-family route-readiness report

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli route-readiness \
  --out .tmp/runs/component_family_route_readiness
```

This produces:

- `component_family_route_readiness.v1.json`
- `component_family_route_readiness.v1.md`

Use this report before choosing the next high-fidelity repair target. It keeps
the formal `aircraft_assembly` route separate from experimental main-wing,
tail, fairing, and `shell_v4` BL-promotion work.

### 6. Write the component-family route smoke matrix

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli component-family-smoke-matrix \
  --out .tmp/runs/component_family_route_smoke_matrix
```

This produces:

- `component_family_route_smoke_matrix.v1.json`
- `component_family_route_smoke_matrix.v1.md`

This is a pre-mesh dispatch smoke only. It checks that main-wing, tail, and
fairing component families classify and dispatch to registered routes without
using `root_last3`; it does not run Gmsh, BL runtime, SU2, or any production
mesh promotion.

### 7. Write the main-wing route-readiness report

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-route-readiness \
  --out .tmp/runs/main_wing_route_readiness
```

This produces:

- `main_wing_route_readiness.v1.json`
- `main_wing_route_readiness.v1.md`

This report reads the committed main-wing geometry / mesh / SU2 / solver reports
and summarizes each stage as real evidence, synthetic wiring evidence, or absent
evidence. It does not run Gmsh or SU2. The current snapshot is
`solver_executed_not_converged`: real geometry, real mesh handoff, real SU2
handoff, and a bounded solver smoke exist, but the convergence gate fails and
reference geometry remains a provenance blocker.

### 8. Write the fairing solid real-geometry smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli fairing-solid-real-geometry-smoke \
  --out .tmp/runs/fairing_solid_real_geometry_smoke
```

This produces:

- `fairing_solid_real_geometry_smoke.v1.json`
- `fairing_solid_real_geometry_smoke.v1.md`

This is provider-only evidence for a real fairing source path. It consumes the
external `HPA-Fairing-Optimization-Project` `best_design.vsp3`, selects an
OpenVSP `Fuselage`, materializes a normalized STEP through
`openvsp_surface_intersection`, and observes closed-solid topology. It does not
run Gmsh meshing, SU2, BL runtime, or convergence.

### 9. Probe the real fairing mesh handoff

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli fairing-solid-real-mesh-handoff-probe \
  --out .tmp/runs/fairing_solid_real_mesh_handoff_probe
```

This produces:

- `fairing_solid_real_mesh_handoff_probe.v1.json`
- `fairing_solid_real_mesh_handoff_probe.v1.md`

This bounded probe uses the real fairing VSP geometry and runs the current
`gmsh_closed_solid_volume` handoff route with coarse probe sizing. The current
result is `mesh_handoff_pass`: `mesh_handoff.v1` is written with a
component-owned `fairing_solid` marker and a `farfield` marker. It does not run
SU2, BL runtime, or convergence.

### 10. Write the fairing solid mesh-handoff smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli fairing-solid-mesh-handoff-smoke \
  --out .tmp/runs/fairing_solid_mesh_handoff_smoke
```

This produces:

- `fairing_solid_mesh_handoff_smoke.v1.json`
- `fairing_solid_mesh_handoff_smoke.v1.md`

This is the first real Gmsh handoff smoke for `fairing_solid`. It emits
`mesh_handoff.v1` for a synthetic closed-solid fixture, but it still does not
run SU2. It does include a component-owned `fairing_solid` force marker in the
mesh-handoff evidence.

### 11. Write the fairing solid SU2-handoff smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli fairing-solid-su2-handoff-smoke \
  --out .tmp/runs/fairing_solid_su2_handoff_smoke
```

This produces:

- `fairing_solid_su2_handoff_smoke.v1.json`
- `fairing_solid_su2_handoff_smoke.v1.md`

This consumes the synthetic closed-solid fairing mesh handoff and materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without executing `SU2_CFD`.
It consumes the component-owned `fairing_solid` wall marker; real fairing
geometry, solver history, and convergence remain blocking gates.

### 12. Write the fairing solid real SU2-handoff probe

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli fairing-solid-real-su2-handoff-probe \
  --out .tmp/runs/fairing_solid_real_su2_handoff_probe \
  --source-mesh-probe-report docs/reports/fairing_solid_real_mesh_handoff_probe/fairing_solid_real_mesh_handoff_probe.v1.json
```

This produces:

- `fairing_solid_real_su2_handoff_probe.v1.json`
- `fairing_solid_real_su2_handoff_probe.v1.md`

This consumes the real fairing `mesh_handoff.v1` probe and materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without executing
`SU2_CFD`. The current committed result owns the `fairing_solid` force marker
and has `reference_geometry_status=warn`, so solver and coefficient claims
remain blocked until reference policy and convergence evidence are explicit.

### 13. Probe the fairing solid reference policy

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli fairing-solid-reference-policy-probe \
  --out .tmp/runs/fairing_solid_reference_policy_probe
```

This produces:

- `fairing_solid_reference_policy_probe.v1.json`
- `fairing_solid_reference_policy_probe.v1.md`

This reads the neighboring fairing optimization project and compares its SU2
reference policy against the legacy pre-standard hpa-mdo real fairing handoff
artifact. The committed result is `reference_mismatch_observed`: external
fairing evidence uses `REF_AREA=1.0`, `REF_LENGTH=2.82880659`, and `V=6.5`,
while that older handoff artifact wrote `REF_AREA=100`, `REF_LENGTH=1`, and
`V=10`. `V=10` is not the HPA standard.

### 14. Write the fairing solid reference-override SU2 handoff probe

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli fairing-solid-reference-override-su2-handoff-probe \
  --out .tmp/runs/fairing_solid_reference_override_su2_handoff_probe
```

This produces:

- `fairing_solid_reference_override_su2_handoff_probe.v1.json`
- `fairing_solid_reference_override_su2_handoff_probe.v1.md`

This consumes the reference-policy probe and the real fairing SU2 handoff probe,
then materializes a corrected `su2_handoff.v1` with `reference_mode=user_declared`.
The current committed result applies `REF_AREA=1.0`, `REF_LENGTH=2.82880659`,
`V=6.5`, density, and viscosity from the neighboring fairing project while
keeping the hpa-mdo `fairing_solid` force marker. It does not run `SU2_CFD`,
does not emit convergence, and keeps moment coefficients blocked because the
moment origin is still borrowed as zero-origin evidence.

### 15. Write the main wing ESP-rebuilt geometry smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-esp-rebuilt-geometry-smoke \
  --out .tmp/runs/main_wing_esp_rebuilt_geometry_smoke
```

This produces:

- `main_wing_esp_rebuilt_geometry_smoke.v1.json`
- `main_wing_esp_rebuilt_geometry_smoke.v1.md`

This is provider-only evidence for the real main-wing source path. It consumes
`data/blackcat_004_origin.vsp3`, selects the OpenVSP `Main Wing`, and
materializes an ESP-normalized STEP with provider topology evidence. It does
not run Gmsh, SU2, BL runtime, or convergence.

### 16. Probe the real main wing mesh handoff

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-real-mesh-handoff-probe \
  --out .tmp/runs/main_wing_real_mesh_handoff_probe \
  --global-min-size 0.35 \
  --global-max-size 1.4
```

This produces:

- `main_wing_real_mesh_handoff_probe.v1.json`
- `main_wing_real_mesh_handoff_probe.v1.md`

This probe uses the real ESP/VSP `Main Wing` geometry and runs the current
`gmsh_thin_sheet_surface` route in a bounded child process. The current result
is `mesh_handoff_pass`: the coarse bounded route writes `mesh_handoff.v1` with
`main_wing`, `farfield`, and `fluid` groups (`97299` nodes and `584460` volume
elements in the committed snapshot). It does not run BL runtime, and this sizing
is not a production default.

The default probe sizing is `--global-min-size 0.2 --global-max-size 0.8`.
Those flags are intentionally probe-local knobs for bounded meshability
experiments; changing them does not change the production route default.

### 17. Materialize the real main wing SU2 handoff

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-real-su2-handoff-probe \
  --out .tmp/runs/main_wing_real_su2_handoff_probe \
  --source-mesh-probe-report docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.json \
  --max-iterations 12
```

This consumes the real main-wing `mesh_handoff.v1` and materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` with `V=6.5 m/s` and a
component-owned `main_wing` force marker. It does not run `SU2_CFD`. The
`--max-iterations` knob is probe-local and exists for bounded solver-budget
campaigns; it does not change production defaults.

### 18. Run the real main wing solver smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-real-solver-smoke-probe \
  --out .tmp/runs/main_wing_real_solver_smoke_probe \
  --source-su2-probe-report docs/reports/main_wing_real_su2_handoff_probe/main_wing_real_su2_handoff_probe.v1.json \
  --timeout-seconds 180
```

This executes `SU2_CFD` from the real main-wing SU2 handoff and writes
`history.csv`, `solver.log`, and `convergence_gate.v1.json`. The committed
result is `solver_executed_but_not_converged`: exit code 0 is solver-execution
evidence only, not convergence.

### 19. Check main wing reference geometry provenance

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-reference-geometry-gate \
  --out .tmp/runs/main_wing_reference_geometry_gate
```

This writes a report-only gate. The committed result is `warn`: the declared
33 m full span cross-checks against real geometry bounds, but the 1.05 m
reference chord and quarter-chord moment origin are still not independently
certified.

### 20. Write the main wing mesh-handoff smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-mesh-handoff-smoke \
  --out .tmp/runs/main_wing_mesh_handoff_smoke
```

This produces:

- `main_wing_mesh_handoff_smoke.v1.json`
- `main_wing_mesh_handoff_smoke.v1.md`

This is a real Gmsh non-BL handoff smoke for `main_wing`. It emits
`mesh_handoff.v1` for a synthetic thin closed-solid wing slab with
component-owned `main_wing` / `farfield` markers. It does not run BL runtime, SU2, or a
convergence gate, and it does not prove real aerodynamic main-wing geometry.

### 21. Write the main wing SU2-handoff smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-su2-handoff-smoke \
  --out .tmp/runs/main_wing_su2_handoff_smoke
```

This produces:

- `main_wing_su2_handoff_smoke.v1.json`
- `main_wing_su2_handoff_smoke.v1.md`

This consumes the synthetic non-BL main-wing mesh handoff and materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without executing `SU2_CFD`.
It consumes the component-owned `main_wing` wall marker, but this is synthetic
wiring evidence only. Real main-wing mesh/SU2/solver artifacts are tracked by
the real probes above.

### 22. Write the tail wing ESP-rebuilt geometry smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli tail-wing-esp-rebuilt-geometry-smoke \
  --out .tmp/runs/tail_wing_esp_rebuilt_geometry_smoke
```

This produces:

- `tail_wing_esp_rebuilt_geometry_smoke.v1.json`
- `tail_wing_esp_rebuilt_geometry_smoke.v1.md`

This is provider-only evidence for the real tail source path. It consumes
`data/blackcat_004_origin.vsp3`, selects the OpenVSP `Elevator` as
`tail_wing` / `horizontal_tail`, and materializes an ESP-normalized STEP. It
does not run Gmsh, SU2, BL runtime, or convergence.

### 23. Write the tail wing mesh-handoff smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli tail-wing-mesh-handoff-smoke \
  --out .tmp/runs/tail_wing_mesh_handoff_smoke
```

This produces:

- `tail_wing_mesh_handoff_smoke.v1.json`
- `tail_wing_mesh_handoff_smoke.v1.md`

This is a real Gmsh non-BL handoff smoke for `tail_wing`. It emits
`mesh_handoff.v1` for a synthetic thin closed-solid tail slab with
component-owned `tail_wing` / `farfield` markers. It does not run BL runtime,
SU2, or a convergence gate, and it does not prove real aerodynamic tail geometry.

### 24. Write the tail wing SU2-handoff smoke

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli tail-wing-su2-handoff-smoke \
  --out .tmp/runs/tail_wing_su2_handoff_smoke
```

This produces:

- `tail_wing_su2_handoff_smoke.v1.json`
- `tail_wing_su2_handoff_smoke.v1.md`

This consumes the synthetic non-BL tail-wing mesh handoff and materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without executing `SU2_CFD`.
It consumes the component-owned `tail_wing` wall marker; real tail geometry,
solver history, and convergence remain blocking gates.

### 25. Probe the real tail wing mesh handoff

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli tail-wing-real-mesh-handoff-probe \
  --out .tmp/runs/tail_wing_real_mesh_handoff_probe
```

This produces:

- `tail_wing_real_mesh_handoff_probe.v1.json`
- `tail_wing_real_mesh_handoff_probe.v1.md`

This probe intentionally records the current blocker instead of forcing a pass.
The real ESP tail geometry materializes as surface-only STEP evidence
(`surface_count=6`, `volume_count=0`), while the current
`gmsh_thin_sheet_surface` external-flow route expects OCC volumes. The next
architecture choice is provider-side solidification/capping or a baffle-volume
route.

### 26. Probe the real tail wing surface mesh

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli tail-wing-surface-mesh-probe \
  --out .tmp/runs/tail_wing_surface_mesh_probe
```

This produces:

- `tail_wing_surface_mesh_probe.v1.json`
- `tail_wing_surface_mesh_probe.v1.md`

This probe confirms the real ESP tail surfaces can be meshed by Gmsh as 2D
surface evidence (`surface_element_count=2286`) with a `tail_wing` physical
group. It intentionally does not emit `mesh_handoff.v1`: there is no farfield
volume, no fluid volume, no SU2-ready external-flow mesh, and no solver run.

### 27. Probe naive tail wing solidification

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli tail-wing-solidification-probe \
  --out .tmp/runs/tail_wing_solidification_probe
```

This produces:

- `tail_wing_solidification_probe.v1.json`
- `tail_wing_solidification_probe.v1.md`

This probe tries bounded Gmsh `healShapes(..., sewFaces=True,
makeSolids=True)` variants on the real ESP tail surfaces. The current result is
`no_volume_created`: the best attempt creates 12 surfaces and 0 volumes. The
next implementation should build explicit caps or a baffle-volume route, not
continue tuning naive heal settings.

### 28. Probe explicit tail wing volume routes

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli tail-wing-explicit-volume-route-probe \
  --out .tmp/runs/tail_wing_explicit_volume_route_probe
```

This produces:

- `tail_wing_explicit_volume_route_probe.v1.json`
- `tail_wing_explicit_volume_route_probe.v1.md`

This probe tries the next serious real-tail route candidates. The current
result is `explicit_volume_route_blocked`: `occ.addSurfaceLoop(...,
sewing=True)` plus `occ.addVolume(...)` creates one explicit volume candidate,
but its signed volume is negative and the farfield cut does not yield a valid
external-flow boundary. The baffle-fragment candidate creates a fluid/farfield
topology, but current duplicated baffle surfaces still fail 3D meshing with a
PLC intersection. It remains report-only and does not emit `mesh_handoff.v1`.

## Artifact Contracts

- [`GeometryProviderResult`](docs/contracts/GeometryProviderResult.md)
- [`mesh_handoff.v1`](docs/contracts/mesh_handoff.v1.md)
- [`su2_handoff.v1`](docs/contracts/su2_handoff.v1.md)
- [`convergence_gate.v1`](docs/contracts/convergence_gate.v1.md)
- [`mesh_study.v1`](docs/contracts/mesh_study.v1.md)
- [`component_family_route_smoke_matrix.v1`](docs/contracts/component_family_route_smoke_matrix.v1.md)
- [`fairing_solid_real_geometry_smoke.v1`](docs/contracts/fairing_solid_real_geometry_smoke.v1.md)
- [`fairing_solid_real_mesh_handoff_probe.v1`](docs/contracts/fairing_solid_real_mesh_handoff_probe.v1.md)
- [`fairing_solid_real_su2_handoff_probe.v1`](docs/contracts/fairing_solid_real_su2_handoff_probe.v1.md)
- [`fairing_solid_reference_policy_probe.v1`](docs/contracts/fairing_solid_reference_policy_probe.v1.md)
- [`fairing_solid_reference_override_su2_handoff_probe.v1`](docs/contracts/fairing_solid_reference_override_su2_handoff_probe.v1.md)
- [`fairing_solid_mesh_handoff_smoke.v1`](docs/contracts/fairing_solid_mesh_handoff_smoke.v1.md)
- [`fairing_solid_su2_handoff_smoke.v1`](docs/contracts/fairing_solid_su2_handoff_smoke.v1.md)
- [`main_wing_esp_rebuilt_geometry_smoke.v1`](docs/contracts/main_wing_esp_rebuilt_geometry_smoke.v1.md)
- [`main_wing_real_mesh_handoff_probe.v1`](docs/contracts/main_wing_real_mesh_handoff_probe.v1.md)
- [`main_wing_real_su2_handoff_probe.v1`](docs/contracts/main_wing_real_su2_handoff_probe.v1.md)
- [`main_wing_real_solver_smoke_probe.v1`](docs/contracts/main_wing_real_solver_smoke_probe.v1.md)
- [`main_wing_reference_geometry_gate.v1`](docs/contracts/main_wing_reference_geometry_gate.v1.md)
- [`main_wing_mesh_handoff_smoke.v1`](docs/contracts/main_wing_mesh_handoff_smoke.v1.md)
- [`main_wing_su2_handoff_smoke.v1`](docs/contracts/main_wing_su2_handoff_smoke.v1.md)
- [`tail_wing_esp_rebuilt_geometry_smoke.v1`](docs/contracts/tail_wing_esp_rebuilt_geometry_smoke.v1.md)
- [`tail_wing_real_mesh_handoff_probe.v1`](docs/contracts/tail_wing_real_mesh_handoff_probe.v1.md)
- [`tail_wing_surface_mesh_probe.v1`](docs/contracts/tail_wing_surface_mesh_probe.v1.md)
- [`tail_wing_solidification_probe.v1`](docs/contracts/tail_wing_solidification_probe.v1.md)
- [`tail_wing_explicit_volume_route_probe.v1`](docs/contracts/tail_wing_explicit_volume_route_probe.v1.md)
- [`tail_wing_mesh_handoff_smoke.v1`](docs/contracts/tail_wing_mesh_handoff_smoke.v1.md)
- [`tail_wing_su2_handoff_smoke.v1`](docs/contracts/tail_wing_su2_handoff_smoke.v1.md)
- [`reference / force-surface provenance gates`](docs/contracts/provenance_gates.md)

## Capability Boundaries

| Area | Status | Notes |
| --- | --- | --- |
| `openvsp_surface_intersection` provider | formal `v1` | `.vsp3 -> normalized STEP -> topology report` |
| `aircraft_assembly` family dispatch | formal `v1` | provider-aware + geometry-family-first |
| Gmsh backend for `thin_sheet_aircraft_assembly` | formal `v1` | real external-flow volume mesh |
| `mesh_handoff.v1` | fixed contract | downstream mesh handoff |
| `su2_handoff.v1` | fixed contract | baseline case materialization + history parse |
| `convergence_gate.v1` | fixed contract | machine-readable mesh / iterative / overall comparability gate |
| Reference provenance gate | fixed contract | `geometry_derived`, `baseline_envelope_derived`, or `user_declared` |
| Force-surface provenance gate | fixed contract | supports whole-aircraft wall and component-owned `fairing_solid` / lifting-surface markers |
| `esp_rebuilt` | experimental | native OpenCSM rule-loft provider is runnable on this machine; main-wing coarse bounded mesh evidence exists, but the provider route is still not a formal production CFD path |
| `main_wing` non-BL route | experimental | real ESP/VSP geometry, real coarse bounded `mesh_handoff.v1`, real `su2_handoff.v1`, and solver-executed evidence now exist; convergence gate fails and reference chord / moment-origin provenance remains `warn`, so it is not productized CFD |
| `tail_wing` non-BL smoke | experimental | real ESP/VSP provider geometry, surface-mesh, naive-solidification, and explicit-volume-route probes exist; real volume mesh handoff is still blocked by surface-only provider output, negative signed-volume surface-loop behavior, and baffle-fragment PLC failure; synthetic `mesh_handoff.v1` / `su2_handoff.v1` materialization smokes exist but are not real tail mesh evidence |
| `fairing_solid` closed-solid route | experimental | real fairing VSP geometry smoke exists for `best_design` Fuselage with `1 body / 8 surfaces / 1 volume`; bounded real-geometry mesh handoff now writes `mesh_handoff.v1` with a `fairing_solid` marker; real-geometry `su2_handoff.v1` materialization exists; external fairing reference policy is applied in a gated override handoff; solver, convergence, and owned moment-origin policy are not productized |
| Other component families | experimental | schema/dispatch exists, but route-specific mesh/SU2 evidence is incomplete |
| Component-family route readiness | report-only `v1` | emits current route status so root_last3 / shell_v4 does not get mistaken for the product mainline |
| Component-family route smoke matrix | report-only `v1` | pre-mesh dispatch smoke for main-wing / tail / fairing route skeletons; no Gmsh, no SU2, no BL runtime |
| Mesh study | formal minimal `v1` | three-tier baseline study that emits `mesh_study.v1` and decides whether the baseline stays `run_only` or can move to `preliminary_compare` |
| Alpha sweep | roadmap | after the chosen mesh/runtime clears the mesh-study verdict |
| Component-level force mapping | roadmap | not implemented yet |

## Recommended Next Gates

1. `alpha sweep`, but only after `mesh_study.v1` says the baseline is at least `preliminary_compare`
2. fix main-wing reference chord / moment-origin provenance, then run a bounded longer-iteration solver campaign; do not treat the current smoke as converged
3. run a real fairing solver smoke now that drag/reference normalization is explicit; keep moment coefficients blocked until moment-origin policy is owned
4. repair explicit tail volume orientation or baffle-surface ownership before solver claims
5. component-level force mapping

ESP/OpenCSM can remain experimental until it earns a separate formal promotion.
