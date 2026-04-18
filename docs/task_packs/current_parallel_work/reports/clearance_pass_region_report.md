# Track T — Clearance Pass Region Bounded Search Report

> 文件性質：真實 bounded search / analysis report
> 任務日期：2026-04-19
> 任務目標：回答 `candidate_rerun_vspaero` + 已修好的 parser/runtime + 已修好的 wire-truss convergence 前提下，固定 replay seed 與 `rib_zonewise=off` 時，`target_shape_z_scale` 往上調後第一個 `ground_clearance` 過線區間在哪裡。

## 1. 結論

- 有，第一個確認到的 `clearance-pass region` 已經找到。
- 第一個 confirmed pass sample 在：
  - `target_shape_z_scale = 3.875`
  - `dihedral_exponent = 2.2`
- 第一個剛過線的 bracket 目前可收斂到：
  - `3.75 < target_shape_z_scale <= 3.875`
- 在這個區間附近，`total_structural_mass_kg` 幾乎不變，約：
  - `21.740 kg`
- failure 沒有轉移成新的 failing gate：
  - `3.75` 以及更低倍率仍然只 fail 在 `ground_clearance`
  - `3.875` / `4.0` 之後 `overall_feasible=true`
  - pass 後最緊的 active-wall signal 變成 `main_radius_taper_margin_min_m`，但它不是新的 fail gate
- 下一步建議：
  - 直接進 `Track R`
  - 不需要另外再開一包大的 clearance refinement
  - 但 `Track R` 建議從 pass-side seed 開始，優先用 `target_shape_z_scale=3.875`（或保守一點用 `4.0`），並留意這是一個只有毫米級 margin 的窄區間

## 2. 固定基準

本次搜尋固定沿用已驗證的 `22 kg` replay seed，只改 outer knob：

- `target_mass_kg = 22.0`
- `aero_source_mode = candidate_rerun_vspaero`
- `rib_zonewise_mode = off`
- `dihedral_exponent = 2.2`
- 固定 reduced vars：
  - `main_plateau_scale = 1.14`
  - `main_taper_fill = 0.7999996000159808`
  - `rear_radius_scale = 1.1199999675573244`
  - `rear_outboard_fraction = 1.0`
  - `wall_thickness_fraction = 0.04630959736295326`
- 其他執行條件：
  - `--skip-local-refine`
  - `--no-ground-clearance-recovery`
  - `--skip-step-export`
  - `--cobyla-maxiter 160`

## 3. 執行命令

以下模板命令重複執行於不同 `target_shape_z_scale`：

```bash
./.venv/bin/python scripts/direct_dual_beam_inverse_design.py \
  --config configs/blackcat_004.yaml \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --output-dir /tmp/clearance_pass_region_search/case_z<SCALE> \
  --target-mass-kg 22 \
  --aero-source-mode candidate_rerun_vspaero \
  --rib-zonewise-mode off \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --dihedral-exponent 2.2 \
  --target-shape-z-scale <SCALE> \
  --no-ground-clearance-recovery
```

所有結果彙整 JSON：

- `/tmp/clearance_pass_region_search/search_results.json`

## 4. Bounded Search Results

| `target_shape_z_scale` | `dihedral_exponent` | `total_structural_mass_kg` | `jig_ground_clearance_min_m` | `overall_feasible` | `target_mass_passed` | `failures` | `primary_driver` |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| `1.7` | `2.2` | `21.740001` | `-0.691912` | `false` | `true` | `["ground_clearance"]` | `ground clearance` |
| `2.0` | `2.2` | `21.740001` | `-0.499717` | `false` | `true` | `["ground_clearance"]` | `ground clearance` |
| `2.3` | `2.2` | `21.740001` | `-0.351352` | `false` | `true` | `["ground_clearance"]` | `ground clearance` |
| `2.6` | `2.2` | `21.740001` | `-0.249518` | `false` | `true` | `["ground_clearance"]` | `ground clearance` |
| `3.0` | `2.2` | `21.740001` | `-0.114263` | `false` | `true` | `["ground_clearance"]` | `ground clearance` |
| `3.5` | `2.2` | `21.740001` | `-0.025592` | `false` | `true` | `["ground_clearance"]` | `ground clearance` |
| `4.0` | `2.2` | `21.740001` | `0.000621` | `true` | `true` | `[]` | `main_radius_taper_margin_min_m` |

### Bracket Refine

| `target_shape_z_scale` | `dihedral_exponent` | `total_structural_mass_kg` | `jig_ground_clearance_min_m` | `overall_feasible` | `target_mass_passed` | `failures` | `primary_driver` |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| `3.75` | `2.2` | `21.740001` | `-0.004863` | `false` | `true` | `["ground_clearance"]` | `ground clearance` |
| `3.875` | `2.2` | `21.740001` | `0.001115` | `true` | `true` | `[]` | `main_radius_taper_margin_min_m` |

## 5. 判讀

### 第一個可能的 clearance-pass region 在哪裡？

- 目前最合理的答案是：
  - `3.75 < target_shape_z_scale <= 3.875`
- 如果只看你原先指定的 coarse list：
  - 第一個 pass 點在 `4.0`
- 如果把小範圍 bracket refine 算進去：
  - 第一個 confirmed pass sample 是 `3.875`

### 這個區間下 mass 大概是多少？

- 幾乎固定在：
  - `21.740 kg`
- 這代表這輪 pass/fail 主因真的就是 clearance，不是 mass tradeoff 突然惡化。

### failure 是否從 `ground_clearance` 轉移到別的 gate？

- 在 fail 區間內，沒有。
  - `1.7` 到 `3.75` 全部都還是只 fail 在 `ground_clearance`
- 在 pass 區間內，也沒有出現新的 failing gate。
  - `3.875` / `4.0` 都是 `overall_feasible=true`
  - 最緊的 active-wall signal 變成 `main_radius_taper_margin_min_m`
  - 但它只是新的 tight margin，不是新的 fail

### 下一步應該直接進 `Track R`，還是還要先做一包 clearance refinement？

- 建議直接進 `Track R`。
- 理由：
  - 這次 bounded search 已經明確回答「要不要把倍率再往上找」這個問題：答案是要，而且第一個 pass 區間已經找到。
  - 不需要再開一包大的 clearance refinement 才能繼續。
  - `Track R` 現在已經可以用 pass-side seed 重新測 `off` vs `limited_zonewise`，看是否終於能得到非 sentinel、而且 clearance 不再卡死的可比 signal。
- 但要保留一個風險註記：
  - 目前 pass margin 很薄，只有毫米級
  - 所以 `Track R` 最好先從 `z_scale=3.875` 或 `4.0` 開始
  - 如果 rib mode / seed 微擾又把 clearance 拉回負值，再回來做一個更窄的 clearance-margin refinement 就好，不必先獨立開一大包

## 6. 最小必要驗證與風險

- 最小必要驗證：
  - 共跑 `9` 個真實 case
  - 全部都走到 `analysis complete`
  - 沒有掉回 parser/runtime blocker
  - 沒有掉回 explicit wire-truss convergence blocker
- 主要風險：
  - pass region 很窄，`3.75` 與 `3.875` 之間只有 `~6 mm` clearance 差距就跨線
  - 這代表之後如果引入新的 seed、rib mode、或別的 outer-loop 微調，clearance 可能再度掉回 fail-side
- 未完成處：
  - 這一包只回答 `rib_zonewise=off` 的 pass region
  - 還沒有驗證同一 pass-side seed 下，`limited_zonewise` 是否仍維持 clearance pass
