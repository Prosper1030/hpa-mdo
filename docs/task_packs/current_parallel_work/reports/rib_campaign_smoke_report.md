# Track R — Repaired-Shortlist Rib Smoke Replay Report

> 文件性質：post-fix repaired-shortlist rerun-aero smoke report
> 任務來源：`docs/task_packs/current_parallel_work/prompts/track_r_repaired_shortlist_rib_smoke.md`
> 更新日期：2026-04-19
> Verdict：**SANE**

## 1. TL;DR

- 這次不再用舊的 suspicious mass seeds，而是直接採用 post-fix repaired AVL-first shortlist 的前兩個 priority seeds：
  - `x3.75`
  - `x3.5`
- 我實際跑了 `4` 組 confirm-level replay：
  - `x3.75 / rib_zonewise=off`
  - `x3.75 / rib_zonewise=limited_zonewise`
  - `x3.5 / rib_zonewise=off`
  - `x3.5 / rib_zonewise=limited_zonewise`
- 四組都是真實 `candidate_rerun_vspaero` 路線，且 selected-case 全部不是 sentinel fallback：
  - `feasible = true`
  - `selected message = analysis complete`
  - `ground_clearance_recovery_triggered = false`
  - `selected_attempt_label = baseline_requested`
- 所以這包最核心的問題，現在答案已經變成：
  - **是，repaired shortlist 上已經可以找到不是 sentinel fallback 的可比 selected-case。**
- 但同時也要講清楚：
  - 在這次最小必要 smoke budget 下，`off` 和 `limited_zonewise` 的 selected-case 指標完全重合到機器精度
  - 唯一有變的是 `rib_design.design_key`
    - `off -> legacy_uniform`
    - `limited_zonewise -> baseline_uniform`
- 這代表：
  - rerun-aero smoke 已經不再是 `BLOCKED` 或 sentinel-driven `SUSPICIOUS`
  - 但目前 repaired shortlist 上也**還沒有出現真正的 rib ranking delta**
- 這次建議的下一步不是開 `Track M` 或 `Track N`，而是：
  - **先停在目前結果**

## 2. 這次實際採用的 repaired shortlist seeds

seed 來源直接依照 `docs/task_packs/current_parallel_work/reports/avl_postfix_shortlist_refresh_report.md` 的 post-fix canonical shortlist：

| Seed | shortlist role | 為什麼先跑它 |
| --- | --- | --- |
| `x3.75` | `Priority 1` | repaired AVL-first refresh 的第一個 seed，也是最穩的第一個 rib smoke seed |
| `x3.5` | `Priority 2` | 同一 repaired shortlist 中 trim AoA 最低、L/D 最好，適合作為第二個 low-AoA baseline compare |

這次**沒有**直接擴到 `x3.875` / `x4.0` / `x4.25`，理由是：

- 使用者要求先做最小必要驗證
- 前兩個 priority seeds 已經足夠回答 prompt 的核心問題：
  - 有沒有 non-sentinel comparable selected-case
  - 目前 `off` vs `limited_zonewise` 有沒有實質 ranking signal

## 3. 實際執行命令

以下命令皆在 repo root `/Volumes/Samsung SSD/hpa-mdo` 下執行：

```bash
./.venv/bin/python scripts/direct_dual_beam_inverse_design.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_75_off \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --aero-source-mode candidate_rerun_vspaero \
  --target-shape-z-scale 3.75 \
  --dihedral-exponent 1.0 \
  --rib-zonewise-mode off \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-step-export \
  --skip-local-refine \
  --cobyla-maxiter 160

./.venv/bin/python scripts/direct_dual_beam_inverse_design.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_75_limited \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --aero-source-mode candidate_rerun_vspaero \
  --target-shape-z-scale 3.75 \
  --dihedral-exponent 1.0 \
  --rib-zonewise-mode limited_zonewise \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-step-export \
  --skip-local-refine \
  --cobyla-maxiter 160

./.venv/bin/python scripts/direct_dual_beam_inverse_design.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_5_off \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --aero-source-mode candidate_rerun_vspaero \
  --target-shape-z-scale 3.5 \
  --dihedral-exponent 1.0 \
  --rib-zonewise-mode off \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-step-export \
  --skip-local-refine \
  --cobyla-maxiter 160

./.venv/bin/python scripts/direct_dual_beam_inverse_design.py \
  --config configs/blackcat_004.yaml \
  --output-dir /tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_5_limited \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --aero-source-mode candidate_rerun_vspaero \
  --target-shape-z-scale 3.5 \
  --dihedral-exponent 1.0 \
  --rib-zonewise-mode limited_zonewise \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-step-export \
  --skip-local-refine \
  --cobyla-maxiter 160
```

Scratch outputs 都寫到：

- `/tmp/hpa_mdo_track_r_repaired_shortlist_20260419/`

沒有把 solver artifacts 寫回 repo 內 `output/`。

## 4. 是否真的跑到 `candidate_rerun_vspaero`

有，而且這四組都是完整的 candidate-owned rerun confirm。

| Seed | `off` 完成 | `limited_zonewise` 完成 | `aero_source_mode` | `baseline_load_source` | `refresh_load_source` | `selected_cruise_aoa_deg` | recovery |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `x3.75` | `yes` | `yes` | `candidate_rerun_vspaero` | `candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun` | `candidate_owned_twist_refresh_from_rerun_sweep` | `1.0` | `not triggered` |
| `x3.5` | `yes` | `yes` | `candidate_rerun_vspaero` | `candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun` | `candidate_owned_twist_refresh_from_rerun_sweep` | `1.0` | `not triggered` |

對應 refresh summary / report 都在：

- `/tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_75_off/`
- `/tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_75_limited/`
- `/tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_5_off/`
- `/tmp/hpa_mdo_track_r_repaired_shortlist_20260419/x3_5_limited/`

## 5. `off` vs `limited_zonewise` 比較表

### 5.1 Selected-case compare

| seed | mode | `objective_value_kg` | `total_structural_mass_kg` | `jig_ground_clearance_min_m` | `target_shape_error_max_m` | `loaded_shape_main_z_error_max_m` | `rib_design.design_key` | `rib_design.effective_warping_knockdown` | `rib_design.unique_family_count` | `rib_design.family_switch_count` | `rib_design.objective_penalty_kg` |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| `x3.5` | `off` | `21.790001142849658` | `21.740001142849657` | `0.048622143329446046` | `1.1102230246251565e-16` | `0.0` | `legacy_uniform` | `0.5` | `1` | `0` | `0.0` |
| `x3.5` | `limited_zonewise` | `21.790001142849658` | `21.740001142849657` | `0.048622143329446046` | `1.1102230246251565e-16` | `0.0` | `baseline_uniform` | `0.5` | `1` | `0` | `0.0` |
| `x3.75` | `off` | `21.790001142849707` | `21.740001142849657` | `0.054090220710290765` | `1.7763568394002505e-15` | `4.440892098500626e-16` | `legacy_uniform` | `0.5` | `1` | `0` | `0.0` |
| `x3.75` | `limited_zonewise` | `21.790001142849707` | `21.740001142849657` | `0.054090220710290765` | `1.7763568394002505e-15` | `4.440892098500626e-16` | `baseline_uniform` | `0.5` | `1` | `0` | `0.0` |

### 5.2 Seed-wise delta summary

| seed | `objective_value_kg` delta (`limited - off`) | `mass` delta | `clearance` delta | `target error` delta | `loaded-shape Z error` delta | meaningful rib delta? |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `x3.5` | `0.0` | `0.0` | `0.0` | `0.0` | `0.0` | `no` |
| `x3.75` | `0.0` | `0.0` | `0.0` | `0.0` | `0.0` | `no` |

### 5.3 這張表實際代表什麼

- 這次已經不是舊報告那種：
  - sentinel fallback
  - `1e12 / inf / -inf`
  - rerun-aero 或 inner solve 崩掉後只能硬讀 fail-side影子
- 現在拿到的是：
  - 真正可比的 selected-case
  - 而且四組都 `feasible=true`
- 但目前這兩個 repaired shortlist seeds 上，`limited_zonewise` 仍然沒有表現出任何比 `off` 更強或更弱的 selected-case差異
- 在 selected-case 層級，`limited_zonewise` 現在看起來更像：
  - **一個會把 label 換成 `baseline_uniform` 的同值 baseline**
  - 還不是會改變 ranking 的 rib-on mode

## 6. 工程判讀

這次 Track R 最重要的結論有三個：

1. repaired-shortlist rerun smoke 已經不再被 sentinel fallback 卡住。
   這是這包最重要的修正結果。現在可以明確回答：**有 non-sentinel 的 comparable selected-case。**

2. 目前沒有看到真正的 rib ranking signal。
   這不是因為 solver fail，而是因為 `limited_zonewise` 在這兩個 priority seeds 上選出來的 effective contract 與 `off` 完全等價：
   - 同一個 `effective_warping_knockdown = 0.5`
   - 同一個 `unique_family_count = 1`
   - 同一個 `family_switch_count = 0`
   - 同一個 `objective_penalty_kg = 0.0`

3. 因此這包現在不支持往 `Track M` 或 `Track N` 繼續推。
   - 不適合進 `Track M`
     - 因為 `Track M` 應該建立在「有真實 signal 但 ranking suspicious」之上
     - 這次不是 suspicious ranking，而是沒有 delta
   - 也不適合進 `Track N`
     - 因為目前沒有任何 rib-on finalist uplift 值得做 finalist spot-check

白話講：

- 這包現在的正確答案不是「rib 已經有用了」
- 而是：
  - **rerun-aero smoke 已經 sane**
  - **但目前 repaired shortlist 上，`limited_zonewise` 還沒有提供會改變 selected-case 的訊號**

## 7. Verdict

**SANE**

理由：

- 不是 `BLOCKED`
  - 四組 command 都完整跑完
  - `candidate_rerun_vspaero` contract 正常
  - 沒有 ground-clearance recovery 介入，也沒有 sentinel fallback
- 也不再是前一輪那種 `SUSPICIOUS`
  - 這次 selected-case 是真實、可比、可重播的
- 但 `SANE` 不代表 rib 已經有 ranking uplift
  - 它只代表：這次 smoke 的答案是乾淨的，而且答案本身就是「目前沒有 delta」

## 8. 建議下一步

**先停在目前結果**

原因：

- 這次沒有 evidence 支持 `Track M`
- 這次也沒有 rib-on finalist 可以支撐 `Track N`
- 如果之後真的要繼續擴，只建議用非常小的 follow-on budget：
  - 先補 `x3.875`
  - 若還是完全同值，再視需要補 `x4.0`

但在目前這包的任務邊界內，沒有必要為了「一定要看到差異」而硬把 smoke 擴成新一輪 coarse search。

## 9. 最小必要驗證、風險、未完成處

### 最小必要驗證

- 已真實跑 `2` 個 repaired-shortlist priority seeds
- 已完成每個 seed 的：
  - `rib_zonewise=off`
  - `rib_zonewise=limited_zonewise`
- 已確認四組都是：
  - `candidate_rerun_vspaero`
  - non-sentinel selected-case
  - `feasible=true`
  - `analysis complete`

### 主要風險

- 這次只覆蓋前兩個 priority seeds，還沒有覆蓋 `x3.875` / `x4.0` / `x4.25`
- 所以目前最強的結論是：
  - repaired shortlist 的中心 seeds 已經 sane
  - 但還不能宣稱整個 shortlist 每個點都一定完全同值

### 未完成處

- 這包沒有把 smoke 擴到第 `3` 或第 `4` 個 seed
- 這包也沒有做任何 code tuning
- 這包沒有改 `scripts/`、`src/`、`tests/`
- 這包只完成一件事：
  - 用 repaired AVL-first canonical shortlist 的前兩個 priority seeds
  - 真實重跑 `candidate_rerun_vspaero`
  - 回答目前 `off` vs `limited_zonewise` 是否已經有 non-sentinel compare，以及目前有沒有 ranking delta
