# Track X — Repaired AVL Recovered Shortlist Rebuild

> 目標：在 Track V / W / Y 都已收斂之後，用 repaired AVL-first path 重新建立後續設計工作真正該用的 recovered shortlist。

## 前提

這包 **一定要等 Track Y 驗證通過後** 才能做。

## 為什麼現在要做這包

Track U 之前的 shortlist / smoke 下游，建立在一條 drift 過、而且一度 selected state 也選錯的 `candidate_avl_spanwise` path 上。
如果 Track V / W / Y 已經證明 repaired AVL path 回到你原本要的版本，那下一步就不應該直接回去用舊 shortlist 繼續跑 rib smoke。

你要做的是：

> 用 repaired AVL-first path，重新找出 `2 到 4` 個真正值得往下送的 recovered candidates。

## 寫入範圍

你只能新增或修改：

- `docs/task_packs/current_parallel_work/reports/repaired_avl_shortlist_report.md`

不要改 code。

## 不要碰

- `README.md`
- `CURRENT_MAINLINE.md`
- `docs/GRAND_BLUEPRINT.md`
- `configs/blackcat_004.yaml`
- 任一 `scripts/*.py`
- 任一 `tests/*.py`

## 你要怎麼做

1. 用 repaired AVL-first path 跑一個 bounded search
2. 優先沿用已知有效的 recovery 經驗：
   - `dihedral_exponent = 2.2`
   - `pass-side z_scale` 先從 `3.875` / `4.0` 一帶開始
3. 先用 `rib_zonewise = off`
4. 目標不是找 final winner，而是找：
   - gate 比較乾淨
   - clearance 已 pass
   - mass 不離譜
   - 後續值得送去 confirm / rib smoke 的 seeds

## 你最後要交付的東西

報告裡至少要有：

1. shortlist seeds（`2 到 4` 個）
2. 每個 seed 的：
   - `multiplier / z_scale`
   - `dihedral_exponent`
   - `aero status`
   - `clearance`
   - `mass`
   - `why this seed matters`
3. 明確推薦：
   - 下一個 `Track R` 先用哪個 seed
   - 哪個 seed 最值得先做 `rib_zonewise=off` vs `limited_zonewise`
   - 哪些 seed 只值得做 confirm，不值得進 rib smoke

## 成功標準

- 不是只說「有幾個看起來不錯」
- 而是真的把後續 `Track R` 的 seed 選擇重新基準化
- 讓下一個 agent 不需要再自己猜到底該先跑哪個 repaired candidate
