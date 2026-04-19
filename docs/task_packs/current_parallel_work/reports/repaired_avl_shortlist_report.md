# Track X — Repaired AVL Recovered Shortlist Rebuild

> 文件性質：Track X 真實 bounded search / handoff report
> 任務日期：2026-04-19
> 任務目標：在 Track V / W / Y 已收斂後，用 repaired AVL-first path 重新建立後續 `Track R` 真正該用的 recovered shortlist。

## 1. 結論

- 這次 bounded search **沒有**找到任何一個「full-gate 乾淨、而且 repaired AVL-first 自己就能過結構 clearance」的 `candidate_avl_spanwise` seed。
- full-gate repaired AVL search（`x3.75` 到 `x4.25`）全部都卡在：
  - `aero_performance:trim_aoa_exceeds_limit`
  - trim AoA 約 `12.515` 到 `12.558 deg`
  - 但 stability / beta / spiral 都還在可接受側，L/D 約 `41.47` 到 `41.55`
- 把同一個 bounded window 改成 `--skip-aero-gates` 後，結構 follow-on 都真的跑完了，且：
  - `total_structural_mass_kg` 幾乎固定在 `21.740001 kg`
  - `jig_ground_clearance_min_m` 隨 multiplier 單調改善
  - 但 `x3.75` 到 `x4.25` 仍然全部 fail 在 `ground_clearance`
- 所以這次 Track X 交出去的 shortlist，正確定位不是：
  - 「已經 fully clean 的 AVL-first winners」
- 而是：
  - **repaired AVL ranking + Track T rerun pass-side bridge**
  - 讓下一個 agent 不要再沿用 drift 過的舊 seeds，但也不要把 repaired AVL screening 誤當成已經完整解掉 trim / clearance。

## 2. 固定基準

這次搜尋固定沿用 Track T / Track Y 已驗證的同一組 structural seed，只掃 outer knob：

- `aero_source_mode = candidate_avl_spanwise`
- `rib_zonewise_mode = off`
- `dihedral_exponent = 2.2`
- fixed structural grids:
  - `main_plateau_grid = 1.0`
  - `main_taper_fill_grid = 0.999999500019976`
  - `rear_radius_grid = 0.9999997444012075`
  - `rear_outboard_grid = 1.0`
  - `wall_thickness_grid = 0.04630959736295326`
- bounded multiplier / `target_shape_z_scale` window:
  - `3.75`
  - `3.875`
  - `4.0`
  - `4.125`
  - `4.25`

Track T 的 confirm-level anchor 仍然保留：

- `candidate_rerun_vspaero` 在 `x3.875` 已經是第一個 confirmed pass sample
- `candidate_rerun_vspaero` 在 `x4.0` 也已確認 `overall_feasible=true`
- 但這包的工作不是重跑 rerun，而是先回答 repaired AVL-first shortlist 該怎麼重建

## 3. 實際執行命令

### 3.1 full-gate repaired AVL-first bounded search

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --base-avl data/blackcat_004_full.avl \
  --output-dir /tmp/track_x_repaired_avl_shortlist_20260419 \
  --aero-source-mode candidate_avl_spanwise \
  --rib-zonewise-mode off \
  --multipliers 3.75,3.875,4.0,4.125,4.25 \
  --dihedral-exponent 2.2 \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160
```

### 3.2 stability-only repaired AVL follow-on search

因為 3.1 全部在 structural follow-on 前就被 `trim_aoa_exceeds_limit` 擋住，為了回答「到底 repaired AVL path 下哪些 seed 還值得往 confirm / rib smoke 送」，我再加跑一輪最小必要的 stability-only bounded search：

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --base-avl data/blackcat_004_full.avl \
  --output-dir /tmp/track_x_repaired_avl_shortlist_20260419_skip_aerogates \
  --aero-source-mode candidate_avl_spanwise \
  --rib-zonewise-mode off \
  --multipliers 3.75,3.875,4.0,4.125,4.25 \
  --dihedral-exponent 2.2 \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160 \
  --skip-aero-gates
```

## 4. Bounded Search Results

### 4.1 full-gate repaired AVL screening

| multiplier / `z_scale` | `dihedral_exponent` | aero status | trim AoA [deg] | L/D | beta / spiral | structural follow-on | reject reason |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| `3.750` | `2.2` | `stable` | `12.51463` | `41.554` | pass | skipped | `aero_performance:trim_aoa_exceeds_limit` |
| `3.875` | `2.2` | `stable` | `12.52495` | `41.533` | pass | skipped | `aero_performance:trim_aoa_exceeds_limit` |
| `4.000` | `2.2` | `stable` | `12.53560` | `41.513` | pass | skipped | `aero_performance:trim_aoa_exceeds_limit` |
| `4.125` | `2.2` | `stable` | `12.54654` | `41.494` | pass | skipped | `aero_performance:trim_aoa_exceeds_limit` |
| `4.250` | `2.2` | `stable` | `12.55779` | `41.475` | pass | skipped | `aero_performance:trim_aoa_exceeds_limit` |

判讀：

- 這一帶不是「完全壞掉」，因為：
  - AVL stability / beta / spiral 沒有翻車
  - trim 也有收斂出 AoA
- 真正卡的是：
  - full-gate trim AoA 仍然略高於 gate 上限
- 所以 full-gate repaired AVL-first path 在這個視窗內，還無法直接產出乾淨 shortlist

### 4.2 stability-only repaired AVL structural follow-on

| multiplier / `z_scale` | `dihedral_exponent` | selection | mass [kg] | clearance [mm] | wire margin [N] | primary structural blocker |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `3.750` | `2.2` | `rejected` | `21.740001` | `-24.585` | `1830.235` | `ground_clearance` |
| `3.875` | `2.2` | `rejected` | `21.740001` | `-24.147` | `1833.753` | `ground_clearance` |
| `4.000` | `2.2` | `rejected` | `21.740001` | `-23.716` | `1837.378` | `ground_clearance` |
| `4.125` | `2.2` | `rejected` | `21.740001` | `-23.288` | `1841.113` | `ground_clearance` |
| `4.250` | `2.2` | `nearest_candidate` | `21.740001` | `-22.862` | `1844.903` | `ground_clearance` |

判讀：

- repaired AVL structural side的主要訊號其實很一致：
  - mass 幾乎不動
  - clearance 隨 multiplier 單調改善
  - 但直到 `x4.25` 還沒過線
- 這代表：
  - repaired AVL screening 目前還不能自己把 Track T 的 rerun pass-side region 重新「內建成 pass」
  - 但它可以提供一個**穩定、可排序**的 repaired ranking

補充推論：

- 若只把這個 stability-only clearance trend 當局部線性訊號看，從 `x3.75 -> x4.25` 只回收了約 `1.723 mm` clearance
- 這個斜率非常淺，所以現在再把 repaired AVL bounded search 大幅往外擴，性價比不高
- 這是一個**由本次資料推得的局部推論**，不是新的物理真值

## 5. Repaired Shortlist

這次我建議交給下一包的 shortlist 是 `4` 個 seeds：

| Priority | multiplier / `z_scale` | `dihedral_exponent` | repaired AVL aero status | repaired AVL clearance [mm] | mass [kg] | why this seed matters | 下一步建議 |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| `1` | `4.000` | `2.2` | `stable` but full-gate `trim_aoa_exceeds_limit` | `-23.716` | `21.740001` | repaired AVL ranking 已進前段，且 Track T rerun confirm 已知 `x4.0` 可 pass；是 repaired shortlist 與 confirm-level pass evidence 的最佳橋接點 | **Track R 第一個 `off` vs `limited_zonewise` seed** |
| `2` | `4.250` | `2.2` | `stable` but full-gate `trim_aoa_exceeds_limit` | `-22.862` | `21.740001` | 這輪 repaired AVL bounded search 的最佳 nearest-candidate；如果 `x4.0` 還是看不到 rib signal，這個點最值得當第二個高機率 confirm seed | **Track R 第二優先 smoke seed** |
| `3` | `4.125` | `2.2` | `stable` but full-gate `trim_aoa_exceeds_limit` | `-23.288` | `21.740001` | 介於 `x4.0` 與 `x4.25` 之間，可用來驗證 repaired AVL ranking 與 rerun confirm 是否保持單調 | **Track R 備用 smoke seed** |
| `4` | `3.875` | `2.2` | `stable` but full-gate `trim_aoa_exceeds_limit` | `-24.147` | `21.740001` | Track T 的第一個 confirmed rerun pass sample；很有診斷價值，但 repaired AVL 這邊仍明顯 fail clearance，適合看 AVL-vs-rerun gap，不適合當第一個 rib smoke 點 | **先做 confirm，不建議當第一個 rib smoke** |

### 為什麼沒有把 `x3.75` 放進 shortlist

- `x3.75` 比 `x3.875` 更差，且沒有額外的新資訊
- 如果你要看 pass-side 邊界，`x3.875` 已經同時具備：
  - repaired AVL bounded search 內的近邊界位置
  - Track T rerun confirm 的第一個 pass-side anchor
- 所以 `x3.75` 不值得再佔一個 shortlist 名額

## 6. 對 Track R 的明確建議

### 6.1 下一個 `Track R` 先用哪個 seed

- **先用 `x4.0`。**

原因：

- 它不是 repaired AVL ranking 裡最極端的外推點
- 它也不是最脆弱的邊界點
- 同時它已經有 Track T 的 confirm-level pass evidence
- 這讓它成為：
  - repaired shortlist
  - 與
  - `candidate_rerun_vspaero` 真實可跑 pass-side seed
  - 之間最安全的橋

### 6.2 哪個 seed 最值得先做 `off` vs `limited_zonewise`

- **`x4.0` 第一個**
- **`x4.25` 第二個**

建議順序：

1. `x4.0`
2. `x4.25`
3. `x4.125`

理由：

- `x4.0` 先回答「最保守的 repaired-shortlist bridge seed 能不能出真 signal」
- 如果 `x4.0` 還是 sentinel，`x4.25` 就是最合理的下一個更強 clearance buffer
- `x4.125` 再補中間點，避免直接只做兩端

### 6.3 哪些 seed 只值得做 confirm，不值得先進 rib smoke

- `x3.875`

理由：

- 它對「AVL-first 與 rerun confirm 的 gap 到底有多大」很有價值
- 但作為第一個 rib smoke seed 太脆
- 若一開始就用它，很容易把 boundary fragility 與 rib signal 混在一起

## 7. 最小必要驗證、風險、未完成處

### 最小必要驗證

- 真實跑了 `2` 輪 bounded search：
  - `1` 輪 full-gate repaired AVL-first campaign
  - `1` 輪 `--skip-aero-gates` repaired AVL structural follow-on campaign
- 共 `10` 個 multiplier cases 都有真實 AVL / JSON / report 輸出
- candidate-owned AVL artifact 與 repaired inverse-design follow-on 都落在：
  - `/tmp/track_x_repaired_avl_shortlist_20260419/`
  - `/tmp/track_x_repaired_avl_shortlist_20260419_skip_aerogates/`

### 主要風險

- repaired AVL-first path 在這個 pass-side window 內，full-gate 仍然全部被 `trim_aoa_exceeds_limit` 擋住
- 即使放寬成 stability-only，`x4.25` 也還有 `-22.862 mm` clearance deficit
- 所以這份 shortlist 不能被誤讀成：
  - 「AVL-first 已經自己收成 pass-side winner」

### 未完成處

- 這一包**沒有**重跑 `candidate_rerun_vspaero`
- 這一包也**沒有**重新做 `off` vs `limited_zonewise`
- 下一步仍然應該是進 `Track R`
- 但 `Track R` 要明確以這份 shortlist 的順序與定位為準，不要再回去用 drift 過的舊 baseline seeds
