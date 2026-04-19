# Track Z — AVL Baseline Exponent Rebaseline

> 目標：確認 `dihedral_exponent = 1.0` 才是舊 AVL-first 主線的 canonical screening baseline，`2.2` 只保留為 recovery / sensitivity 選項。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/task_packs/current_parallel_work/README.md`
6. `docs/task_packs/current_parallel_work/reports/repaired_avl_shortlist_report.md`
7. `docs/task_packs/current_parallel_work/reports/avl_structural_loadstate_alignment_report.md`
8. `docs/dihedral_sweep_phase2_report.md`
9. `docs/Manual/avl_doc.txt`

## 問題定義

使用者已明確指出：

- 舊版 multiplier 本來就已經是 tip-weighted
- 舊主線的 `dihedral_exponent` baseline 是 `1.0`
- `2.2` 是後來 Track T ground-clearance recovery ladder 引入的 heuristic

所以這包的任務不是再往更高 multiplier 推，也不是直接接受 `2.2` 當新基準。

你要回答的是：

1. repaired AVL-first path 下，`exp = 1.0` vs `exp = 2.2` 的差異到底有多大？
2. `2.2` 是否只能合理地留在 recovery / sensitivity，而不能當 screening baseline？
3. 在 **`exp = 1.0`** 基準下，後續真正該用的 repaired shortlist 是哪些 seeds？

## 寫入範圍

你只能新增或修改：

- `docs/task_packs/current_parallel_work/reports/avl_baseline_exponent_rebaseline_report.md`

不要改 code。

## 不要碰

- `README.md`
- `CURRENT_MAINLINE.md`
- `docs/GRAND_BLUEPRINT.md`
- `configs/blackcat_004.yaml`
- 任一 `scripts/*.py`
- 任一 `tests/*.py`

## 你要怎麼做

1. 用 repaired AVL-first path 做一個 bounded compare
2. 同一組 structural seed、同一組 multiplier 視窗，至少比較：
   - `dihedral_exponent = 1.0`
   - `dihedral_exponent = 2.2`
3. multiplier 視窗至少包含：
   - `3.5`
   - `3.75`
   - `3.875`
   - `4.0`
   - `4.25`
4. 先用 `rib_zonewise = off`
5. full-gate 和必要時的 stability-only follow-on 都要如實寫出，不要混淆

## 你最後要交付的東西

報告裡至少要有：

1. `exp = 1.0` vs `2.2` 的 apples-to-apples 比較表
   - `multiplier / z_scale`
   - `dihedral_exponent`
   - `trim AoA`
   - `L/D`
   - `structure_status`
   - `mass`
   - `clearance`
   - `reject reason`
2. 明確回答：
   - 舊主線 baseline 應不應該回到 `exp = 1.0`
   - `2.2` 應不應該只保留在 recovery / sensitivity
3. 基於 `exp = 1.0` 的 canonical shortlist seeds（`2 到 4` 個）
4. 明確推薦：
   - 下一個 `Track R` 先用哪個 seed
   - 哪個 seed 第二個跑
   - 哪個 seed 只適合做 confirm，不適合第一個 rib smoke

## 成功標準

- 不是繼續為 `2.2` 辯護
- 而是把 baseline 和 recovery 角色切回正確位置
- 讓後續 `Track R` 不再建立在錯的 baseline 上
