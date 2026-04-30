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
- `main_wing` / `tail_wing` / `fairing_solid` / `fairing_vented` 的 schema、family dispatch、route registry 已經存在；`main_wing` 已有 real ESP/VSP geometry、real Gmsh mesh handoff、real SU2 handoff、solver executed but not converged artifact、reference-geometry warn gate，以及 station-seam BRep / same-parameter / ShapeFix / export-source / export-strategy / internal-cap / profile-resample strategy / profile-resample BRep validation / profile-resample repair feasibility / profile parametrization audit / side-aware parametrization candidate / side-aware BRep validation / mesh-quality hotspot evidence；目前主翼產品化 blocker 是 station PCurve / export repair，不是 production CFD pass；`tail_wing` 已有 real geometry / surface / blocker probes，`fairing_solid` 已有 real VSP geometry smoke、bounded real mesh handoff probe、real SU2 handoff materialization probe 與 external reference override handoff，但都還不是正式可交付 CFD 路徑。
- 目前只有 `gmsh_thin_sheet_aircraft_assembly` 會走真實 Gmsh meshing；其他 route 會回 `route_stage=placeholder`。
- `shell_v4` 是 BL / solver-entry diagnostic branch，不是任意主翼 product route；BL route 只有在 hpa-mdo owns transition sleeve / receiver faces / interface loops / layer-drop events 之後才可 promotion。

## ESP Reality Check

- `esp_rebuilt` 在目前 `main` 上已經不再是 `not_materialized` stub。它現在會走 native OpenCSM lifting-surface rebuild：從 `.vsp3` 讀 wing/tail sections，生成 rule-loft `.csm`，再用 `serveCSM -batch` 輸出 normalized STEP 與 topology artifact。
- 這台 Mac mini M4（macOS 26.4.1 / arm64）目前可用的 runtime truth 是：`serveESP` / `serveCSM` 在 `PATH` 上、`ocsm` 仍缺席，但 batch 路徑可以直接用 `serveCSM`。所以 `detect_esp_runtime()` 會回 `available=true`、`batch_binary=serveCSM`，provider 已可執行。
- 2026-04-30 的 `main_wing_esp_rebuilt_geometry_smoke.v1` 已經把主翼單體 real geometry evidence 收進 committed report：它從 `blackcat_004_origin.vsp3` 選到 `Main Wing`，產生 normalized STEP，topology 為 `1 body / 32 surfaces / 1 volume`。
- 目前真正的 blocker 已經往後移：coarse bounded real mesh handoff 和 real SU2 handoff 都已經 materialize，`SU2_CFD` 也能執行並寫出 `history.csv`；但 12-iteration smoke 和 OpenVSP-reference 80-iteration follow-up 都是 `fail/not_comparable`，80-iteration run 已保留 `surface.csv` 與 `forces_breakdown.dat`，main-wing reference chord 已可用 OpenVSP/VSPAERO `cref` cross-check，reference area / moment origin 仍是比較性 blocker。後續 station-seam evidence 又把更早的幾何 blocker 定位到曲線 36 / 50：PCurves 存在，但 curve-3D-with-PCurve / same-parameter / vertex-tolerance checks 不一致，`BRepLib.SameParameter` tolerance sweep 不能修復，25 次 `ShapeFix_Edge` operation/tolerance 組合也不能修復；export-source audit 進一步確認 `rebuild.csm` 是單一 OpenCSM `rule` loft over 11 sketch sections，兩個 defect station 都落在 internal rule sections。split-bay export-strategy probe 能把 target stations 變成 rule boundaries，但 no-union candidate 是 3 volumes，union candidate 雖是 1 volume 卻沒有保住 full-span `y=-16.5..16.5 m` bounds；internal-cap probe 又確認 no-union 在兩個 target stations 都有 duplicate cap faces，而 union 在 `y=13.5 m` 留下 6 個 cap fragments 並截斷右半翼。profile-resample strategy probe 則把來源 section profile counts 從 `57/59` 統一到 `59`、保持單一 `rule`，materialize 成 `1 volume / 32 surfaces` 且 target stations 無 cap faces；profile-resample BRep validation 再用 candidate station-y geometry 選出 6 條 station edges，確認 PCurves 存在但 curve-3D-with-PCurve / same-parameter-by-face / vertex-tolerance-by-face 仍 suspect；profile-resample repair feasibility 對 6 條 station edges 跑 25 個 ShapeFix / SameParameter operation-tolerance 組合，`recovered_attempt_count = 0`；profile parametrization audit 進一步把 4 條短 station curves 對回 terminal `linseg` fragments、2 條長 station curves 對回 spline rest arcs，且 6 條 station-edge PCurve consistency 全失敗；side-aware parametrization candidate 已保留 TE/LE anchors、用 30/30 上下表面點數 materialize 成 `1 volume / 32 surfaces` 且無 target station cap faces；side-aware BRep validation 也用 candidate station-y geometry 選出 6 條 station edges，確認沒有 replay 舊 fixture tags，但 6 / 6 station-edge PCurve consistency 仍 fail。mesh-quality hotspot audit 另確認 real mesh 有 `78` 個 ill-shaped tets、`min_gamma=8.131677887160085e-07`，worst-tet sample 多數在 farfield，但仍有 5 / 20 在主翼 surfaces 19 / 29 / 32，其中 surface 19 與 station-seam entity trace 重疊。
- 結論：`esp_rebuilt` 現在是「provider runnable + route artifact exists, but not production CFD」。下一步不是再補 runtime 安裝，也不是宣稱 solver converged；優先修 side-aware OpenCSM/export PCurve generation，之後才考慮 bounded mesh handoff、panel-vs-SU2 force-breakdown、reference provenance 與有根據的 numerics campaign。
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
reference geometry remains a provenance blocker. At the HPA standard flow
condition, the selected real solver smoke has `CL=0.263161913`, below the
main-wing `CL > 1.0` engineering acceptance gate, so it must not be treated as a
pass. The current first next action is
`rebuild_station_pcurves_or_export_station_seams_before_meshing_policy`.

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

There is also a non-default 40-iteration follow-up snapshot at
`docs/reports/main_wing_real_solver_smoke_probe_iter40/`. It improves the gate
to `warn/run_only`, but still remains `solver_executed_but_not_converged`.

An OpenVSP/VSPAERO reference-policy SU2 handoff snapshot is kept at
`docs/reports/main_wing_openvsp_reference_su2_handoff_probe/`. It is explicit
probe-local evidence only: `REF_AREA=35.175`, `REF_LENGTH=1.0425`,
`REF_ORIGIN_MOMENT=(0,0,0)`, `V=6.5`, and `main_wing` force marker ownership
are materialized, but `SU2_CFD` and convergence are not run.

The paired OpenVSP-reference solver smoke is kept at
`docs/reports/main_wing_openvsp_reference_solver_smoke_probe/`. `SU2_CFD`
executes and writes `history.csv`, but the gate is still `fail/not_comparable`;
this is not a convergence pass.

The non-default 40-iteration OpenVSP-reference follow-up is kept at
`docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter40/`. It
improves the gate to `warn/run_only` with `V=6.5`, but still remains
`solver_executed_but_not_converged`.

The current highest committed OpenVSP-reference budget probe is the 80-iteration
snapshot at `docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/`.
It is `fail/not_comparable`: coefficient tails are stable, but residual drop is
still below the pass threshold and the HPA lift gate fails because `CL <= 1.0`.
The rerun now retains both `surface.csv` and `forces_breakdown.dat` in
`artifacts/raw_solver/`, so panel/SU2 force-breakdown debugging is no longer
blocked by missing raw force output.

### 19. Check main wing reference geometry provenance

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-reference-geometry-gate \
  --out .tmp/runs/main_wing_reference_geometry_gate
```

This writes a report-only gate. The committed result is `warn`: the declared
33 m full span cross-checks against real geometry bounds, and the 1.05 m
reference chord cross-checks against OpenVSP/VSPAERO `cref=1.0425 m` within the
pass tolerance. It remains `warn` because applied `REF_AREA=34.65` differs from
OpenVSP/VSPAERO `Sref=35.175` by about 1.49%, and the quarter-chord moment
origin differs from the VSPAERO CG settings.

### 20. Probe main wing station-seam BRep hotspot

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-brep-hotspot-probe \
  --out .tmp/runs/main_wing_station_seam_brep_hotspot_probe
```

This report-only probe reads the real main-wing normalized STEP plus the
station-topology fixture. The current committed result is
`brep_hotspot_captured_station_edges_suspect`: station curves 36 and 50 map to
the expected STEP edges and owner faces 12 / 13 / 19 / 20 have closed,
connected, ordered wires, but PCurve consistency checks remain suspect.

### 21. Probe main wing station-seam same-parameter feasibility

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-same-parameter-feasibility \
  --out .tmp/runs/main_wing_station_seam_same_parameter_feasibility
```

This report-only probe tests whether a simple in-memory
`BRepLib.SameParameter` repair can recover the suspect station edges. The
current committed result is `same_parameter_repair_not_recovered` for tolerance
values from `1e-7` through `1e-3`, so the next geometry gate is PCurve /
station-seam inspection or rebuild rather than promoting a compound meshing
policy or extending solver iterations.

### 22. Probe main wing station-seam ShapeFix feasibility

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-shape-fix-feasibility \
  --out .tmp/runs/main_wing_station_seam_shape_fix_feasibility
```

This report-only probe tests whether bounded in-memory `ShapeFix_Edge`
operations recover the suspect station edges after the same-parameter probe did
not. The current committed result is `shape_fix_repair_not_recovered`: 25
operation/tolerance attempts recover zero station checks. The next gate is
station PCurve rebuild or a different station-seam export strategy.

### 23. Audit main wing station-seam export source

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-export-source-audit \
  --out .tmp/runs/main_wing_station_seam_export_source_audit
```

This report-only audit ties the station-seam blocker back to the generated
OpenCSM export source. The current committed result is
`single_rule_internal_station_export_source_confirmed`: `rebuild.csm` uses one
multi-section `rule` loft over 11 sketch sections, and the suspect station
curves 36 and 50 map to internal rule sections at `y=-10.5 m` and `y=13.5 m`.
The next gate is `prototype_station_seam_export_strategy_before_solver_budget`.

### 24. Probe main wing station-seam export strategy

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-export-strategy-probe \
  --out .tmp/runs/main_wing_station_seam_export_strategy_probe \
  --materialize-candidates
```

This report-only probe materializes split-at-defect-section OpenCSM candidates
under the report artifact directory only. The current committed result is
`export_strategy_candidate_materialized_but_topology_risk`: target stations
move to rule boundaries, but the no-union candidate imports as 3 volumes and
the union candidate loses the full-span y-bound after import. Do not promote
this split-bay candidate as a production default.

### 25. Inspect split-candidate internal caps

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-internal-cap-probe \
  --out .tmp/runs/main_wing_station_seam_internal_cap_probe
```

This report-only probe imports the materialized split candidates through
OCC/Gmsh and counts station-plane faces at the target defect stations. The
current committed result is `split_candidate_internal_cap_risk_confirmed`:
`split_at_defect_sections_no_union` has duplicate cap faces at both target
stations and imports as 3 volumes; `split_at_defect_sections_union` truncates
the right span and leaves 6 cap fragments at `y=13.5 m`. This is negative
evidence for split-bay promotion; the next gate is a PCurve/export rebuild
strategy before mesh handoff or solver-budget work.

### 26. Probe profile-resample station-seam export strategy

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-profile-resample-strategy-probe \
  --out .tmp/runs/main_wing_station_seam_profile_resample_strategy_probe \
  --materialize-candidate
```

This report-only probe keeps the OpenCSM export as a single `rule` and
uniformizes the source section profile point counts. The current committed
result is `profile_resample_candidate_materialized_needs_brep_validation`:
source profiles were `57/59` points, the candidate uses `59` points for every
section, imports as `1 volume / 32 surfaces`, preserves `y=-16.5..16.5 m`, and
has zero station-plane cap faces at `y=-10.5 m` / `13.5 m`. This is not
mesh-ready; the next gate is station BRep/PCurve validation on the candidate
STEP.

### 27. Validate profile-resample station-seam BRep/PCurve

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-profile-resample-brep-validation-probe \
  --out .tmp/runs/main_wing_station_seam_profile_resample_brep_validation_probe
```

This report-only probe reads the profile-resample candidate STEP and selects
station seam edges by candidate station-y geometry, not by replaying old station
fixture curve/surface ids. The current committed result is
`profile_resample_candidate_station_brep_edges_suspect`: six station edges are
found at `y=-10.5 m` and `y=13.5 m`, PCurves are present, and owner-face wires
are closed/connected/ordered, but curve-3D-with-PCurve, same-parameter-by-face,
and vertex-tolerance-by-face checks remain suspect. This keeps the candidate
out of mesh handoff until station PCurve/export consistency is repaired.

### 28. Probe profile-resample station-seam repair feasibility

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-profile-resample-repair-feasibility-probe \
  --out .tmp/runs/main_wing_station_seam_profile_resample_repair_feasibility_probe
```

This report-only probe runs bounded in-memory OCCT ShapeFix / SameParameter
attempts on the candidate-selected station edges. The current committed result
is `profile_resample_station_shape_fix_repair_not_recovered`: all six station
edges still have PCurves, but none of the 25 operation/tolerance combinations
recovers same-parameter, curve-3D-with-PCurve, and vertex-tolerance checks. This
keeps the next fix at export / section parametrization, not direct mesh handoff.

### 29. Audit profile-resample section parametrization

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-profile-parametrization-audit \
  --out .tmp/runs/main_wing_station_seam_profile_parametrization_audit
```

This report-only audit parses the current profile-resample candidate CSM and
correlates candidate station-edge lengths back to CSM section segments. The
current committed result is
`profile_parametrization_seam_fragment_correlation_observed`: all six selected
station-edge PCurve checks fail, four short station curves match terminal
`linseg` fragments, and two long station curves match spline rest arcs. This
keeps the next gate at a side-aware profile parametrization candidate; it is not
a mesh-handoff or solver-convergence claim.

### 30. Probe side-aware profile parametrization

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-side-aware-parametrization-probe \
  --out .tmp/runs/main_wing_station_seam_side_aware_parametrization_probe \
  --materialize-candidate
```

This report-only probe splits each profile into upper and lower sides,
resamples both sides independently to 30 points, preserves TE/LE anchors, and
materializes a single-rule candidate. The current committed result is
`side_aware_parametrization_candidate_materialized_needs_brep_validation`:
`1 volume / 32 surfaces`, full span preserved, no target-station cap faces.
This is still not mesh-ready; the next gate is BRep/PCurve validation on this
side-aware candidate STEP.

### 31. Validate side-aware station-seam BRep/PCurve

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli main-wing-station-seam-side-aware-brep-validation-probe \
  --out .tmp/runs/main_wing_station_seam_side_aware_brep_validation_probe
```

This report-only probe reads the side-aware candidate STEP and selects station
seam edges by candidate station-y geometry, not by replaying old station
fixture curve/surface tags. The current committed result is
`side_aware_candidate_station_brep_edges_suspect`: topology remains
`1 volume / 32 surfaces`, `source_fixture_tags_replayed=false`, but all six
selected station edges still fail PCurve consistency. It is not a mesh-handoff
or solver-convergence claim.

### 32. Write the main wing mesh-handoff smoke

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

### 26. Write the main wing SU2-handoff smoke

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

### 27. Write the tail wing ESP-rebuilt geometry smoke

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

### 28. Write the tail wing mesh-handoff smoke

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

### 29. Write the tail wing SU2-handoff smoke

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

### 30. Probe the real tail wing mesh handoff

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

### 31. Probe the real tail wing surface mesh

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

### 32. Probe naive tail wing solidification

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

### 33. Probe explicit tail wing volume routes

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
- [`main_wing_surface_force_output_audit.v1`](docs/contracts/main_wing_surface_force_output_audit.v1.md)
- [`main_wing_station_seam_brep_hotspot_probe.v1`](docs/contracts/main_wing_station_seam_brep_hotspot_probe.v1.md)
- [`main_wing_station_seam_same_parameter_feasibility.v1`](docs/contracts/main_wing_station_seam_same_parameter_feasibility.v1.md)
- [`main_wing_station_seam_shape_fix_feasibility.v1`](docs/contracts/main_wing_station_seam_shape_fix_feasibility.v1.md)
- [`main_wing_station_seam_export_source_audit.v1`](docs/contracts/main_wing_station_seam_export_source_audit.v1.md)
- [`main_wing_station_seam_export_strategy_probe.v1`](docs/contracts/main_wing_station_seam_export_strategy_probe.v1.md)
- [`main_wing_station_seam_profile_parametrization_audit.v1`](docs/contracts/main_wing_station_seam_profile_parametrization_audit.v1.md)
- [`main_wing_station_seam_side_aware_parametrization_probe.v1`](docs/contracts/main_wing_station_seam_side_aware_parametrization_probe.v1.md)
- [`main_wing_station_seam_side_aware_brep_validation_probe.v1`](docs/contracts/main_wing_station_seam_side_aware_brep_validation_probe.v1.md)
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
| `main_wing` non-BL route | experimental | real ESP/VSP geometry, real coarse bounded `mesh_handoff.v1`, real `su2_handoff.v1`, probe-local OpenVSP reference-policy handoff/smoke, and solver-executed evidence now exist; 12-iteration gates fail, the OpenVSP-reference 80-iteration follow-up is also `fail/not_comparable` after the `CL > 1.0` HPA lift gate, `surface.csv` and `forces_breakdown.dat` are retained for panel/SU2 force-breakdown debug, VSPAERO `CLi` is now source-labeled as inviscid surface integration rather than wake-induced, reference chord now cross-checks against OpenVSP/VSPAERO `cref`, reference-area / moment-origin provenance remains `warn`, and station-seam probes localize a geometry blocker to curves 36 / 50 with no same-parameter or ShapeFix recovery; split-bay export is negative evidence due to multi-volume / span-bound / internal-cap topology, while profile-resample and side-aware exports are single-volume no-target-cap candidates whose candidate-selected station edges still fail BRep/PCurve consistency checks before mesh handoff; mesh-quality hotspot audit keeps the mesh-quality warning honest: worst-tet sample is mostly farfield, but main-wing surfaces 19 / 29 / 32 still appear and surface 19 overlaps the station-seam trace |
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
2. repair side-aware OpenCSM/export PCurve generation before any mesh handoff or solver-budget work
3. use the retained main-wing `forces_breakdown.dat` / `surface.csv` to debug the panel-vs-SU2 lift gap with the source-backed `CLi = inviscid`, `CLiw = wake/free-stream` semantics, then fix reference-area / moment-origin provenance before any larger residual/numerics campaign; do not treat either smoke as converged, and keep `CL > 1.0` as the HPA operating-point acceptance floor
4. run a real fairing solver smoke now that drag/reference normalization is explicit; keep moment coefficients blocked until moment-origin policy is owned
5. repair explicit tail volume orientation or baffle-surface ownership before solver claims
6. component-level force mapping

ESP/OpenCSM can remain experimental until it earns a separate formal promotion.
