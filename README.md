# HPA-MDO：人力飛機新概念設計管線

這個 repo 目前服務的是一條 **全新人力飛機設計 pipeline**，不是 Black Cat 004 舊機體的補強案。
Black Cat 004 / dual-beam / OpenMDAO spar optimizer 仍保留為歷史基礎與可重用工具，但不再是 root
README 的主敘事，也不應被新 agent 當成目前 candidate 的設計真相。

目前正式主線以 Phase J pipeline 為準：

```text
Mission contract
-> tail / CG / trim / stability contract
-> Fourier-AVL calibration
-> Fourier spanload candidate generation
-> smooth production geometry realization
-> AVL realization check with full-aircraft trim / stability context
-> structure-budgeted loaded-Z search
-> AVL recheck on realizable loaded shape and all-moving tail trim
-> Tier2 full-alpha airfoil selection plus discrete tail-airfoil screening
-> aero-structure closure with tail control DOFs
-> FEM/APDL / shell buckling / load-factor / tailboom / hardware checks
```

這條線的目標是把任務需求、spanload、可製造幾何、loaded shape、翼型選擇、結構預算與候選驗證
放在同一條可追溯的工程鏈上。它目前產出的 `current_avl_compromise_conservative_closed` 是
**conservative screening candidate**，可以拿去做幾何 / 結構 / 製造審查，但還不是 final
production aircraft。

如果要看這條 pipeline 每一步現在實際用到哪些 artifact、candidate、關鍵數字與 trust boundary，
先讀 [docs/reports/2026-05-09_phase_j_evidence_map.md](docs/reports/2026-05-09_phase_j_evidence_map.md)。
這份 evidence map 已重新審核 source chain：`sample_1476` / `233 W` / `8642.9 m`
屬於舊 medium-search 診斷資料，不是目前 Phase J 上游證據。commit history 顯示
mission-to-airfoil 線確實存在：pilot power / thermal derate、mission design-space scan、
drag budget、MissionContract / FourierTarget、airfoil sidecar、smooth geometry、loaded-Z、
Tier2 airfoil 與 closure 都已接出來。現在缺的是一份 promoted trace manifest，把 current
mission handoff 乾淨追到 `current_avl_compromise_conservative_closed`；所以目前 go-mode
candidate 是 conservative screening candidate，不是 final aircraft。

如果要看目前 pathfinder 本身的 basis lock，讀
[docs/reports/2026-05-09_pathfinder_basis_lock.md](docs/reports/2026-05-09_pathfinder_basis_lock.md)。
它把 `current_avl_compromise_conservative_closed` 的 downstream artifact chain、
beam-line proxy / aerodynamic surface / clearance / loaded-Z 一致性、以及下一步
tail contract / rib sensitivity / ASWing-like coupling / FEM detail 的優先順序鎖清楚。

如果要做 rib / rear-spar sensitivity，先讀
[docs/reports/2026-05-09_conservative_load_mapper_foundation.md](docs/reports/2026-05-09_conservative_load_mapper_foundation.md)。
`ConservativeLoadMapper` 是 aero grid -> structural grid 的 opt-in conservative remap foundation；
它守恆 total lift、root bending moment、total pitching torque，並輸出 correction diagnostics。
它是 sensitivity 前置基礎，不是 aeroelastic sign-off。

如果要把 horizontal tail / vertical tail 接進目前主線，先讀
[docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md](docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md)。
尾翼不是最後才補的 FEM 件；對 all-moving horizontal tail / all-moving vertical tail 來說，它是
trim、stability、control authority、tailboom load、mission drag/mass 的共同 contract。主翼
Fourier spanload 仍由主翼主導，但 mission contract 必須先有 tail / CG / stability 邊界，
AVL realization 之後必須進 full-aircraft trim / stability context，aero-structure closure 之後
all-moving tail 才能作為控制自由度。

目前 current pathfinder 的 tail contract v0 foundation 已建立，讀
[docs/reports/2026-05-09_tail_contract_v0_foundation.md](docs/reports/2026-05-09_tail_contract_v0_foundation.md)
和 [configs/current_pathfinder_tail_contract_v0.yaml](configs/current_pathfinder_tail_contract_v0.yaml)。
它只完成 tail volume / reserve bookkeeping，screening output 仍是 `required_inputs_missing`；
all-moving full-aircraft AVL audit v0 則在
[docs/reports/2026-05-09_full_aircraft_tail_avl_audit_v0.md](docs/reports/2026-05-09_full_aircraft_tail_avl_audit_v0.md)
與 `output/current_pathfinder_tail_avl_audit_v0/`。本機 AVL runner 已產生 9 個全機 deck /
`.st` sweep artifact，但 verdict 是 `blocked_by_directional_stability_or_vtail_authority`：
longitudinal trim 仍被 missing CG / wing AC 擋住，`V_V = 0.010145` 且
`C_n_beta = 0.002236` 太小。下一步要先回 tail sizing / CG / reference-moment contract，
不要直接跳 rib sensitivity。
目前這一步已往下接出 V-tail / CG reference sizing sensitivity v0，讀
[docs/reports/2026-05-09_vtail_cg_reference_sensitivity_v0.md](docs/reports/2026-05-09_vtail_cg_reference_sensitivity_v0.md)
和 `output/current_pathfinder_vtail_sensitivity_v0/`。它只做 bounded V-tail area / aft-position
AVL sensitivity，不做 rib / rear spar / ASWing-lite / FEM / tail airfoil NSGA2。結果顯示較大的
V-tail area / tail arm 能把 `C_n_beta` 和 `C_n_deltaV` 往合理方向推，但 final verdict 仍是
`blocked_by_missing_cg_or_reference_moment`：`Xref` 只是 AVL coefficient reference，`Xnp` 只是
未驗證 convention 的 neutral-point candidate，current pathfinder 還沒有 promoted aircraft CG range。

接著已建立 tail / CG / trim / stability screening v1，讀
[docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md](docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md)
與 `output/current_pathfinder_tail_cg_trim_stability_v1/`。這一步明確把 AVL `Xref`
設為每個 screening CG row，不把原始 `Xref` 當 CG；`Xnp` 只有在
`Xnp = Xref - Cma/CLa*Cref` 自洽時才使用。verdict 是
`ready_for_tail_aware_rib_rear_spar_sensitivity`，但只限 screening：推薦下一步使用
CG range `[0.68, 0.75] m`、H-tail `S_H=4.5 m^2 / x_ac_H=8.281 m`、V-tail
`S_V=3.36 m^2 / x_ac_V=8.350 m`，並把 tail drag/mass penalty 帶進 sensitivity；
這不是 measured CG manifest、tail polar sign-off、FEM 或硬體認證。

tail-aware bounded rib / rear-spar sensitivity 已完成，讀
[docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md](docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md)。
目前 verdict 是 `ready_for_tail_aware_aeroelastic_closure`，選定 screening basis 是
`0.30 m` rib target bay tied to `121` full-wing materialized rib/station count、
`bounded_50pct_screening` rear-spar participation、warping knockdown `0.50246`。
重要限制：未補償的 tail+ribs mass bookkeeping 會把 CG 推到 `0.801 m`，所以 aeroelastic
closure 只能使用 final CG 管理後的 `0.75 m` screening row；不能把 tail/rib mass 加上去後還
沿用舊 ready verdict。

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
| 看 tail-aware rib / rear-spar sensitivity verdict 與下一步 basis | [docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md](docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md) | ready-for-aeroelastic-closure screening basis |
| 看 all-moving tail / trim / stability 要怎麼進目前 pathfinder | [docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md](docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md) | empennage contract insertion |
| 找所有文件入口 | [docs/README.md](docs/README.md) | 文件索引 |
| 看近期優先順序 | [docs/NOW_NEXT_BLUEPRINT.md](docs/NOW_NEXT_BLUEPRINT.md) | 近期 roadmap，可能需要再按 Phase J 更新 |
| 接續任務包 | [docs/task_packs/current_parallel_work/README.md](docs/task_packs/current_parallel_work/README.md) | 多 agent handoff |
| 查舊 Black Cat / OpenMDAO 內容 | [docs/legacy_blackcat004_downstream_reference.md](docs/legacy_blackcat004_downstream_reference.md) | 歷史參考，不是目前主線 |
| 接續暫停 CFD 支線 | [hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md](hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md) | paused validation route |

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
  sensitivity 已選出可進下一階段的 screening basis，但 final CG 必須被管理在 `[0.68, 0.75] m`。
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
  AVL audit v0，但目前是 blocker report。CG / wing AC、directional stability / authority、
  tail drag-mass contract 還沒 closure，不能宣稱整機 aircraft-feasible。
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
| Empennage / trim / stability | 已有 tail contract v0、all-moving AVL audit v0、V-tail sensitivity v0，以及 tail/CG/trim/stability screening v1；tail-aware rib/rear-spar sensitivity 已把 current pathfinder 推到 `ready_for_tail_aware_aeroelastic_closure`，但 CG 必須用 final managed row，不可用未補償 mass shift |
| V-tail / CG reference sensitivity | v0 顯示 directional derivatives 可被 area/arm 推高；v1 進一步用 explicit CG-referenced AVL rows 驗證 Xnp convention、longitudinal trim、static margin 與 yaw authority |
| Loaded-Z / aero-structure closure | 目前 candidate 是否可推進的核心審查層 |
| Tier2 airfoil selection | 依 actual loaded-shape local `Cl/Re` 做 full-alpha 查表，但 query quality warning 必須保守處理 |
| FEM/APDL / shell / load-factor | candidate spot-check，不是 final sign-off |
| Rib / root / wire hardware / composite detail | 開放 validation blockers，需要後續實體化與 detail evidence |
| SU2 / mesh-native CFD | paused route，不是目前 performance truth |

---

## 給 AI Agent 的規則

- 先讀 [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md)，再讀本 README。
- 不要從舊 Black Cat 004 文件、舊 OpenMDAO DAG 或 `examples/blackcat_004_optimize.py` 反推目前主線。
- 不要把 ignored output 或 legacy diagnostic 直接升格成 current evidence；要先建立 promoted trace。
- 如果完成一系列同屬同一個 idea 的任務，且它改變了目前主線、可用狀態、信任邊界或下一步優先順序，必須同步更新 README / CURRENT_MAINLINE。
- 工程輸出拿到後，要用航空工程角度檢查物理合理性，不要只說測試通過。

---

## License

MIT
