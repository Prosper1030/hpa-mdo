# HPA-MDO — Human-Powered Aircraft Design Pipeline

> ## ⚠️ ARCHIVED / LEGACY DEVELOPMENT REPOSITORY
>
> **This repository preserves the historical development of the HPA-MDO project.
> It is not the recommended starting point.**
>
> The codebase has since been separated into dedicated repositories along trust
> boundaries — stable numerical kernels, meshing/CFD research, and active
> application-level development:
>
> | Repository | Role |
> |---|---|
> | **[hpa-mdo-framework](https://github.com/Prosper1030/hpa-mdo-framework)** | **Start here** — project overview, architecture, verification status |
> | [hpa-core](https://github.com/Prosper1030/hpa-core) | Trusted dual-beam structural analysis kernel |
> | [hpa-meshing](https://github.com/Prosper1030/hpa-meshing) | Geometry / meshing / CFD research line |
> | `hpa-next` | Active application and orchestration workspace (private) |
>
> **What this repository still is:** 1,318 commits of development history from
> 2026-04 to 2026-05, plus the shared git object store for the repositories
> above. It is preserved deliberately, not abandoned — including the parts that
> were later reorganized away. Nothing has been deleted or rewritten.
>
> **For a concise overview of the project, start at
> [hpa-mdo-framework](https://github.com/Prosper1030/hpa-mdo-framework).**

---

以下為原有的歷史開發文件，完整保留。

## 目錄

- [主線操作協議與操作說明](#主線操作協議pathfinder-first-then-expansion) — 原本位於本文件後段
- [WO-006 CFD 開發日誌](docs/wo006_changelog.md) — 2026-05 期間的逐次探針紀錄（原本位於本文件前段）

---

## 主線操作協議：Pathfinder First, Then Expansion

目前策略不是一次把 `22464` 個 mission design-space cases 全部推到最終 FEM，也不是把單一
candidate 當成全域最佳解。正確做法是先選一條最可信的 **pathfinder candidate**，把
mission、Fourier/AVL、smooth geometry、loaded-Z、loaded-shape AVL、Tier2 airfoil、
aero-structure closure、FEM/APDL spot-check 全部串通。

這條 pathfinder 的用途是：

- 先證明整條工程 pipeline 可以從任務需求一路走到可審查候選。
- 在每個 stage 做局部工程修正與局部最佳化，暴露真實 blocker。
- 讓 rib、rear spar、wire attach、root joint、beam-line / aero-surface、airfoil query
  以及 empennage trim / stability 這些問題有同一個候選與同一組 load / geometry / mass basis 可以討論。
- 等閉環穩定後，再擴大 search space：更多 span / AR / speed / airfoil / structure family /
  rib-bracing 方案，而不是一開始就把所有維度全部打開。

因此 `current_avl_compromise_conservative_closed` 應讀成目前的 pathfinder /
conservative screening candidate：它是工程閉環的先行者，不是 final aircraft、不是全域最佳，
也不是硬 gate 標準。

---

## 先看哪裡

| 目的 | 文件 | 定位 |
|---|---|---|
| 判斷目前真正主線 | [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md) | 單一真相文件 |
| 理解主線為什麼變成 Phase J | [docs/reports/2026-05-08_commit_history_report.md](docs/reports/2026-05-08_commit_history_report.md) | commit-derived pipeline report |
| 看 Phase J 每一步目前到底靠哪些 artifact / candidate / trust boundary | [docs/reports/2026-05-09_phase_j_evidence_map.md](docs/reports/2026-05-09_phase_j_evidence_map.md) | stage-by-stage evidence map |
| 看目前 pathfinder 的 locked basis / geometry-state 一致性 / 下一步優先序 | [docs/reports/2026-05-09_pathfinder_basis_lock.md](docs/reports/2026-05-09_pathfinder_basis_lock.md) | candidate basis lock |
| 看 conservative load remap / rib sensitivity 前置 load gate | [docs/reports/2026-05-09_conservative_load_mapper_foundation.md](docs/reports/2026-05-09_conservative_load_mapper_foundation.md) | load conservation foundation |
| 看 tail-aware rib / rear-spar sensitivity verdict 與 material-family compare | [docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md](docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md) | balsa baseline ready-for-closure basis; foam-only families stay low-stiffness references; hybrid rework candidates are listed |
| 看 tail-aware aeroelastic closure verdict | [docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md](docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md) | converged; twist-source audit points to hybrid rib/stiffness rework |
| 看 current pathfinder rib station/bay 是否真的 materialized | [docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md](docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md) | 121 station / 120 bay trace; shape, bond, collar, transition data still blocked |
| 看 rib / rear-spar / torsion blocker 下一階段 verdict | [docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md) | hybrid closure-owned bounded twist clears 3 deg; P1 local load-path has since moved to coupon/local FEM readiness |
| 跑 rib / torsion fast design-search loop 與 FEM calibration sample set | [docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md) | revised link-limited physical model; selected fast candidate is uniform 0.30 m carbon-collar rear75; FEM samples include original selected, aggressive, foam reference, and revised selected |
| 看 rib / torsion fast-loop CCX local-frame physical alignment | [docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md](docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md) | representative structural rows aligned within 5% against local CCX beam-frame; no hidden family correction; not final bond/tube-wall/buckling sign-off |
| 看 rib / torsion detailed local validation shortlist | [docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md](docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md) | selected 10 mm uniform carbon-collar basis locked; 12 mm reserve and 10 mm glass-collar fallback listed; no final aircraft pass |
| 接 positive torque-zone local FEM / coupon package | [docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md](docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md) | R067/R068/R069 + B066-B069 package; APDL skeleton and coupon/missing-data register; no FEM margin claimed |
| 看 P1 local detail Step 1 geometry/allowable freeze sheet | [docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md](docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md) | spar tube OD/wall from config; 8 missing-data items filled; 7 preliminary margins; APDL skeleton filled |
| 看 P1 local detail Step 2 refined analytical margin run | [docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md](docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md) | C04 bond peel margin −0.893 (critical blocker); C07 skin sag pre-strain sweep; C02-C06 analytical margins large |
| C04 collar joint 架構修正方向 + multi-mode design search | `scripts/collar_joint_modes.py` (59 tests) + `scripts/current_pathfinder_rib_collar_joint_design_search.py` (11 tests) | saddle ring yoke confirmed as C04 fix direction; recommended_c04_fix() = saddle ring + clamp; analytical screening only |
| 3 m 翼板 spar splice 設計 | `scripts/current_pathfinder_spar_splice_design.py` (13 tests) | 5 joints per half-wing on structural freeze half-span 16.5 m; all pass; 3.85 kg full-wing; inboard spigot wall 1.02 mm; 3 m limit locked |
| 看 P1 C04 load path 與 mass/CG/tail/closure 回灌後 verdict | [docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md](docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md) | final verdict `p1_local_load_path_ready_for_coupon_fem`; C04 saddle/yoke/clamp + splice mass charged to closure; coupon/local FEM next |
| 接 Baseline A team release package | `output/baseline_A_team_release/` | old `baseline_A_release_system_ready` is historical/generated evidence under data-authority repair, not active current truth; current release status is `baseline_A_data_authority_restored_wo006_unblocked` for bounded WO-006 only |
| 看 Baseline A mass / CG / margin ledger | `output/baseline_A_team_release/margin_budget.md` + `mass_cg_margin_daily_review.md` | old `mass_cg_margin_ledger_ready` is historical/generated evidence under data-authority repair, not active current truth; `98.5 kg` is authority, `106.828608 kg` is suspect screening |
| 看 Baseline A design-space freeze audit | `output/baseline_A_team_release/design_space_freeze_audit/design_space_freeze_audit.md` | `baseline_A_freeze_reasonable`; no explicit nearby dominance trigger; power-budget watch item remains |
| 看 Baseline A manufacturable geometry audit | `output/baseline_A_team_release/manufacturable_geometry_audit/manufacturable_geometry_audit.md` | `geometry_freeze_needs_fix`; smooth enough for release engineering, not shop/RFQ drawing control |
| 看 carbon tube RFQ screening pack | `output/baseline_A_team_release/carbon_tube_rfq_pack.md` | old `carbon_tube_rfq_pack_ready` is historical/generated evidence under data-authority repair, not active current truth; WO-005 is draft/vendor-screening only |
| 讓 AI thread 自動接任務 | [docs/AI_WORK_ORDER_PROTOCOL.md](docs/AI_WORK_ORDER_PROTOCOL.md) + [docs/work_orders/QUEUE.md](docs/work_orders/QUEUE.md) | work-order lifecycle, required report shape, reviewer prompt, priority queue |
| 看 all-moving tail / trim / stability 要怎麼進目前 pathfinder | [docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md](docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md) | empennage contract insertion |
| 找所有文件入口 | [docs/README.md](docs/README.md) | 文件索引 |
| 看近期優先順序 | [docs/NOW_NEXT_BLUEPRINT.md](docs/NOW_NEXT_BLUEPRINT.md) | 近期 roadmap，可能需要再按 Phase J 更新 |
| 接續任務包 | [docs/task_packs/current_parallel_work/README.md](docs/task_packs/current_parallel_work/README.md) | 多 agent handoff |
| 查舊 Black Cat / OpenMDAO 內容 | [docs/legacy_blackcat004_downstream_reference.md](docs/legacy_blackcat004_downstream_reference.md) | 歷史參考，不是目前主線 |
| 接續 mesh-native CFD 支線 | [hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md](hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md) | product-route handoff; separate from WO-006 bounded calibration |

---

## 目前能做什麼

- 用 mission design-space / drag-budget contract 建立 Stage-0 search bounds、mission gate 與 seed pool；
  committed config dry-run 為 `22464` cases，local generated handoff 目前是 ignored output。
- Fourier-AVL calibration 工具與資料格式已存在；目前 committed calibration rows 仍是 legacy diagnostic，
  要做 current candidate ordering 前必須建立 current trace，而不是重用舊 medium-search top exports。
  `scripts/fourier_avl_calibration_mvp.py` 現在要求明確 `--report-json`，舊 medium-search 來源預設封鎖。
- Stage-2 Fourier spanload / MissionContract / FourierTarget machinery 已存在，但還缺一份 promoted
  current trace manifest 連到 go-mode candidate；不要把「缺 trace」誤讀成「Stage 0-2 不存在」。
- 現有 downstream chain 可從 `smooth_tier2_production_baseline` 進入 smooth production geometry / AVL realization。
- 對 realized geometry 做 AVL realization check。
- 做 structure-budgeted loaded-Z search，檢查 mass、clearance、wire、loaded shape 的折衝。
- 對 realizable loaded shape 重跑 AVL，避免拿 requested shape 的漂亮結果當真。
- 用 `ConservativeLoadMapper` 將 AVL/aero grid loads remap 到 structural grid，並檢查 total lift、
  root bending moment、torque 的 conservation diagnostics；large correction 要降級 load basis
  confidence，不能直接進 rib sensitivity。
- 建立 tail / CG / trim / stability 低階 contract，讓 all-moving horizontal tail / vertical tail
  在 mission、full-aircraft AVL recheck、tail-aware closure、tailboom/hardware validation 中有明確位置。
  Current pathfinder v0 foundation、all-moving full-aircraft AVL audit v0、V-tail sensitivity v0
  和 tail / CG / trim / stability screening v1 已存在；tail-aware rib / rear-spar
  sensitivity 已選出可進 aeroelastic closure 的 balsa baseline screening basis，且 material
  family sensitivity 顯示 foam-only EPS/XPS/structural foam 不能直接解除 twist blocker；twist-source
  audit 的 baseline 判定為 `ready_for_hybrid_rib_stiffness_rework`；rib/torsion rework
  verdict 已讓 selected hybrid closure-owned bounded twist 清到 `2.070 deg`，但 direct
  stress-test 仍是 conservative mapping warning；final CG 必須被管理在 `[0.68, 0.75] m`。
- 用 Tier2 full-alpha airfoil database 依 actual loaded-shape local `Cl/Re` 做翼型選擇。
- 做 aero-structure closure，確認氣動、翼型、loaded shape、結構、clearance、wire 在同一個候選上閉合。
- 做 FEM/APDL、shell buckling、load-factor candidate spot-check。
- 用 Phase J 後續 guardrails 防止局部 pass 被誤寫成 final aircraft sign-off。

---

## 不要誤會的地方

- 這不是「Black Cat 004 舊設計補強」的 root workflow。
- `configs/blackcat_004.yaml`、`examples/blackcat_004_optimize.py`、舊 OpenMDAO component DAG、11 根管材描述等都是歷史 / downstream reference。
- FEM/APDL / shell / load-factor checks 目前是 candidate-relevant equivalent-physics validation / spot-check，不是 final composite、root fitting、wire hardware、rib joint 或 flight sign-off。
- Rib / rear spar / wire attach / root joint 是 downstream physical-realization 與 validation 問題；除非它們會改變 aero-structure closure candidate 排序，否則不要把它們升成上游主線。
- Horizontal / vertical tail 不是最後才補的外觀件；current pathfinder 已有 all-moving tail
  AVL audit v0、tail / CG / trim / stability screening v1 與 tail-aware closure evidence。
  目前 CG / trim / static / directional authority 可以在 managed CG row 下成立；P1 C04
  load-path surrogate 也已可進 coupon/local FEM。但 direct spar-pair stress-test、C07
  skin sag process、hardware/laminate detail 和 local FEM/coupon 尚未 sign-off，不能宣稱
  整機 aircraft-feasible。
- 主翼 mesh-native CFD / SU2 線仍暫停，不能拿來當 performance claim truth。

---

## 主要指令

### Mission / upstream concept

```bash
PYTHONPATH=src ./.venv/bin/python scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_upstream_concept_run \
  --worker-mode julia
```

快速 plumbing smoke，不能當工程證據：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir .tmp/birdman_upstream_concept_stubbed \
  --worker-mode stubbed
```

### Phase J pipeline sidecars

這些 script 主要用來重建或刷新 Phase J 目前的候選證據。執行前請先看
[CURRENT_MAINLINE.md](CURRENT_MAINLINE.md) 和 commit-history report，確認輸入 artifacts 是你要的版本。

```bash
PYTHONPATH=src ./.venv/bin/python scripts/fourier_avl_calibration_mvp.py \
  --report-json path/to/current_mission_coupled_spanload_search_report.json
PYTHONPATH=src ./.venv/bin/python scripts/structure_budgeted_z_state_search.py
PYTHONPATH=src ./.venv/bin/python scripts/loaded_shape_avl_recheck_mvp.py
PYTHONPATH=src ./.venv/bin/python scripts/tier2_loaded_shape_airfoil_mvp.py
PYTHONPATH=src ./.venv/bin/python scripts/aero_structure_closure_mvp.py
PYTHONPATH=src ./.venv/bin/python scripts/full_aircraft_tail_avl_audit_v0.py
PYTHONPATH=src ./.venv/bin/python scripts/vtail_cg_reference_sensitivity_v0.py
PYTHONPATH=src ./.venv/bin/python scripts/tail_aware_rib_rear_spar_sensitivity.py
PYTHONPATH=src ./.venv/bin/python scripts/tail_aware_aeroelastic_closure.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_rib_torsion_design_search.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_rib_collar_joint_design_search.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_spar_splice_design.py
PYTHONPATH=src ./.venv/bin/python scripts/current_pathfinder_p1_load_path_mass_closure.py
PYTHONPATH=src ./.venv/bin/python scripts/build_baseline_a_release.py
PYTHONPATH=src ./.venv/bin/python scripts/baseline_a_manufacturable_geometry_audit.py
```

只有在明確做歷史診斷時，才可以加
`--allow-legacy-medium-search` 讀 `birdman_mission_coupled_medium_search_20260503`；
輸出必須標成 legacy diagnostic，不能當 current Phase J evidence。

### Candidate structural spot-checks

```bash
PYTHONPATH=src ./.venv/bin/python scripts/phase15_candidate_load_factor_buckling_check.py
PYTHONPATH=src ./.venv/bin/python scripts/phase16_ccx_buckling_wire6_ramp.py
PYTHONPATH=src ./.venv/bin/python scripts/phase17_candidate_shell_buckling_tip_review.py
```

---

## 安裝

需要 Python 3.10 以上版本。

```bash
git clone https://github.com/Prosper1030/hpa-mdo.git
cd hpa-mdo
uv venv --python 3.10 .venv
source .venv/bin/activate
uv pip install -e ".[all]"
```

外部 VSPAero / OpenVSP / 翼型資料路徑請放在 `configs/local_paths.yaml`，不要直接改主 config：

```bash
cp configs/local_paths.example.yaml configs/local_paths.yaml
```

---

## 目前信任邊界

| 層級 | 目前定位 |
|---|---|
| Mission / concept search | 可用於新設計探索，但仍依賴 proxy 與 worker quality |
| Fourier-AVL / AVL realization | 目前主線氣動篩選與 spanload authority |
| Conservative load remap | rib / rear-spar sensitivity 前置 load gate，不是 aeroelastic sign-off |
| Empennage / trim / stability | 已有 tail contract v0、all-moving AVL audit v0、V-tail sensitivity v0，以及 tail/CG/trim/stability screening v1；tail-aware closure 顯示 managed CG、H-tail trim reserve、static margin、V-tail authority 保留，但 twist-source audit 指向 hybrid rib/stiffness rework；不可用未補償 mass shift |
| V-tail / CG reference sensitivity | v0 顯示 directional derivatives 可被 area/arm 推高；v1 進一步用 explicit CG-referenced AVL rows 驗證 Xnp convention、longitudinal trim、static margin 與 yaw authority |
| Loaded-Z / aero-structure closure | 目前 candidate 是否可推進的核心審查層 |
| Tier2 airfoil selection | 依 actual loaded-shape local `Cl/Re` 做 full-alpha 查表，但 query quality warning 必須保守處理 |
| Manufacturable geometry / discretization | WO-004 判定 smooth pathfinder 可供 release engineering 使用，但連續尺寸仍不是 shop drawing；WO-005 已補 RFQ screening station/span/splice manifest，尚未變成 drawing release |
| FEM/APDL / shell / load-factor | candidate spot-check，不是 final sign-off |
| Rib / root / wire hardware / composite detail | 開放 validation blockers，需要後續實體化與 detail evidence |
| SU2 / mesh-native CFD | WO-006 current-GO no-BL completion case 已有 finite 159-iteration SU2 force history，可作 route-level force evidence；WO-006H reopened campaign 仍標示 BL/core 與 finer no-BL hard limits。下一步是 BL/core conformal topology、near-wall/y+、force ownership 與 grid V&V；目前仍不是 drag/power performance truth |

---

## 給 AI Agent 的規則

- 先讀 [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md)，再讀本 README。
- 接 Baseline A / team work 時，再讀 [docs/AI_WORK_ORDER_PROTOCOL.md](docs/AI_WORK_ORDER_PROTOCOL.md)
  與 [docs/work_orders/QUEUE.md](docs/work_orders/QUEUE.md)。
- 不要從舊 Black Cat 004 文件、舊 OpenMDAO DAG 或 `examples/blackcat_004_optimize.py` 反推目前主線。
- 不要把 ignored output 或 legacy diagnostic 直接升格成 current evidence；要先建立 promoted trace。
- 如果完成一系列同屬同一個 idea 的任務，且它改變了目前主線、可用狀態、信任邊界或下一步優先順序，必須同步更新 README / CURRENT_MAINLINE。
- 工程輸出拿到後，要用航空工程角度檢查物理合理性，不要只說測試通過。

---

## License

MIT
