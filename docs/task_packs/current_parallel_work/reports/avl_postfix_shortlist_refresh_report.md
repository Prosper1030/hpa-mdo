# AVL Post-Fix Shortlist Refresh Report

> 文件性質：post-fix 真實 bounded search / shortlist refresh report
> 任務日期：2026-04-19
> 任務目標：在 recent AVL fixes 已落地後，用 current HEAD 的 repaired AVL-first path 重新刷新 canonical repaired shortlist，避免後續 Track R 繼續建立在 pre-fix shortlist 上。

## 1. 結論

- **是，post-fix 之後，full-gate repaired AVL-first path 已經能自己產生 clean pass-side candidates。**
- 這次在 current HEAD `69af9b9`，固定：
  - `aero_source_mode = candidate_avl_spanwise`
  - `dihedral_exponent = 1.0`
  - `rib_zonewise = off`
  - multipliers = `3.5 / 3.75 / 3.875 / 4.0 / 4.25`
  重新跑最小必要 bounded search 後，**5/5 全部都是 full-gate clean pass**：
  - `trim_aoa_exceeds_limit` 已解除
  - `structure_status = feasible`
  - `reject_reason = none`
  - mass 全部維持在 `21.740001 kg`
  - clearance 全部為正，約 `55.079 mm` 到 `59.508 mm`
- 所以這包現在要交出去的不是「靠 skip-aero-gates 推論出來的 repaired ranking」，而是：
  - **post-fix repaired AVL-first canonical shortlist**
  - 可以直接拿去開 `Track R`
- 這次 **不需要** 再補 `--skip-aero-gates` stability-only follow-on，因為 full-gate 已經自己留下足夠的 pass-side evidence。

## 2. 固定基準

- `aero_source_mode = candidate_avl_spanwise`
- `dihedral_exponent = 1.0`
- `rib_zonewise_mode = off`
- fixed structural grids:
  - `main_plateau_grid = 1.0`
  - `main_taper_fill_grid = 0.999999500019976`
  - `rear_radius_grid = 0.9999997444012075`
  - `rear_outboard_grid = 1.0`
  - `wall_thickness_grid = 0.04630959736295326`
- fixed multiplier / `target_shape_z_scale` window:
  - `3.5`
  - `3.75`
  - `3.875`
  - `4.0`
  - `4.25`

這次納入的已知修正背景，都是 current HEAD 已包含的真實程式狀態：

- `1475034` fix: 修正 `blackcat_004` 主翼 airfoil mapping 與 baseline AVL
- `3f2f816` fix: 修正 AVL aero gate 改用 generated case `Sref`
- `93980c8` fix: 補上 AVL lift gate 近等值容差

## 3. 實際執行命令

### 3.1 full-gate repaired AVL-first bounded search

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --base-avl data/blackcat_004_full.avl \
  --output-dir /private/tmp/track_z_postfix_shortlist_refresh_exp1_fullgate_20260419 \
  --aero-source-mode candidate_avl_spanwise \
  --rib-zonewise-mode off \
  --multipliers 3.5,3.75,3.875,4.0,4.25 \
  --dihedral-exponent 1.0 \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160
```

### 3.2 本次實際輸出路徑

- report: `/private/tmp/track_z_postfix_shortlist_refresh_exp1_fullgate_20260419/dihedral_sweep_report.txt`
- summary CSV: `/private/tmp/track_z_postfix_shortlist_refresh_exp1_fullgate_20260419/dihedral_sweep_summary.csv`
- summary JSON: `/private/tmp/track_z_postfix_shortlist_refresh_exp1_fullgate_20260419/dihedral_sweep_summary.json`

### 3.3 這次沒有補跑的東西

- `--skip-aero-gates` stability-only follow-on

原因很直接：

- full-gate 已經讓 5 個 required multipliers 全部跑到 `reject_reason = none`
- 所以再補 stability-only 不會增加這包最核心的判斷力，反而容易把「真正 full-gate pass」和「只是 follow-on pass」混在一起

## 4. Post-Fix Shortlist Compare

### 4.1 full-gate repaired AVL-first compare

| multiplier / `z_scale` | trim AoA [deg] | L/D | structure status | mass [kg] | clearance [mm] | reject reason |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| `3.5` | `10.13387` | `44.102` | `feasible` | `21.740001` | `55.079` | `none` |
| `3.75` | `10.14945` | `44.064` | `feasible` | `21.740001` | `56.559` | `none` |
| `3.875` | `10.15766` | `44.046` | `feasible` | `21.740001` | `57.298` | `none` |
| `4.0` | `10.16612` | `44.028` | `feasible` | `21.740001` | `58.036` | `none` |
| `4.25` | `10.18384` | `43.994` | `feasible` | `21.740001` | `59.508` | `none` |

### 4.2 直接判讀

- 這次的主訊號已經和 pre-fix Track Z 完全不同：
  - trim AoA 不再卡 `12+ deg`
  - 現在落在 `10.134` 到 `10.184 deg`
  - 全部都低於 hard gate `max_trim_aoa_deg = 12.0`
- 這一個 bounded window 現在已經是：
  - **full-gate clean pass plateau**
  - 不是「整排 trim fail，只能靠 skip-aero-gates 讀結構趨勢」的 fail-side window
- 但也要看懂一個重要細節：
  - 這 5 個點的 campaign score 幾乎完全相同，都是 `21.790001...`
  - 所以 canonical shortlist 的重排，**不能只抄 internal winner label**
  - 應該改用：
    - clean full-gate pass
    - clearance buffer
    - trim / L/D 輕微退化
    - 作為第一個 rib smoke seed 的穩定性
    來做工程排序

## 5. 現在能不能直接開 Track R

- **可以，現在可以直接開 `Track R`。**

原因：

- repaired AVL-first path 已經能自己產生 clean pass-side candidates
- Track R 不再需要建立在 pre-fix fail-side shortlist 或 `skip-aero-gates` 推論上
- 現在最合理的下一步就是：
  - 直接用這份 post-fix canonical shortlist
  - 做 `rib_zonewise=off` vs `limited_zonewise`
  - 看 rib smoke 是否能開始產生真正的非 sentinel ranking signal

唯一要保留的使用邊界是：

- 這 5 個點都略高於 telemetry `soft_trim_aoa_deg = 10.0`
- 但它們不是 hard reject
- 所以 Track R 第一個 seed 還是應優先從較低 trim AoA、但已經有足夠 clearance buffer 的點開始

## 6. New Canonical Shortlist

### 6.1 建議排序

| rank | multiplier / `z_scale` | role | why it belongs here |
| --- | --- | --- | --- |
| `1` | `3.75` | `Priority 1` | current campaign 的 full-gate winner，而且相較 `x3.5` 只付出很小的 aero penalty，就多拿到約 `1.48 mm` clearance buffer；是最穩的第一個 rib smoke seed |
| `2` | `3.5` | `Priority 2` | 全視窗中 trim AoA 最低、L/D 最好，且仍有 `55.079 mm` 正 clearance；適合當第二個低-AoA baseline smoke |
| `3` | `3.875` | `Priority 3` | 仍保有接近 winner 的 aero 表現，同時再多一點 clearance；適合作為第三個 smoke seed 或 bridge seed |
| `4` | `4.0` | `pass-side backup` | 現在已是 clean pass-side backup，不再需要被降成 confirm-only；但作為第一個 rib smoke 沒有比 `x3.75` 更有代表性 |
| `5` | `4.25` | `confirm-only` | 視窗邊界的高-clearance sanity point；clearance 最大，但 trim / L/D 最差，較適合做 confirm，不適合當第一個 rib smoke |

### 6.2 用你要的 shortlist 類別重寫

- `Priority 1`: `x3.75`
- `Priority 2`: `x3.5`
- `Priority 3`: `x3.875`
- `confirm-only`: `x4.25`

補充：

- `x4.0` 現在應該視為 **clean pass-side backup**
- 它不再屬於舊報告裡那種「只能 confirm」的角色

### 6.3 Track R 第一個 seed 應該用哪個

- **`x3.75` / `target_shape_z_scale = 3.75`**

理由：

- 這是 current HEAD full-gate campaign 的 winner
- 相較 `x3.5`，只增加約 `0.0156 deg` trim AoA、損失約 `0.038` L/D
- 但多拿到約 `1.48 mm` clearance buffer
- 比 `x4.0` / `x4.25` 更貼近 restored baseline，而不是又往高 multiplier 習慣漂回去

### 6.4 哪個 seed 只適合 confirm，不適合第一個 rib smoke

- **`x4.25`**

理由：

- 它確實是 clean full-gate pass-side candidate
- 但它代表的是這個視窗的高-clearance 邊界，不是 canonical baseline 的中心點
- 和 `x3.75` 相比，它只多約 `2.95 mm` clearance
- 但 trim AoA 更高、L/D 更差、wire margin 也更低
- 所以它更適合當 post-fix monotonicity / sanity confirm，不適合當第一個 rib smoke

## 7. 對 Pre-Fix Track Z 的修正說明

### 7.1 現在應視為過時的結論

下面這些 pre-fix Track Z 結論，現在都不應再當真：

- 「這個 `exp = 1.0` 視窗在 full-gate 下整排都會卡 `trim_aoa_exceeds_limit`」
- 「repaired AVL-first path 還不能自己產生 clean pass-side candidates」
- 「要先靠 `--skip-aero-gates` 才能看出哪些 seed 值得往下送」
- 「`x4.0` 只適合做 confirm，不適合當第一個 rib smoke」
- 「`x4.25` 不值得進 repaired shortlist，因為 full-gate 沒有 pass-side signal」

現在的真實 post-fix結果是：

- `x3.5` 到 `x4.25` 全部都是 full-gate clean pass
- `x4.0` 已不再是 confirm-only
- full-gate repaired AVL-first path 已經能直接提供 Track R seed

### 7.2 仍然可以保留的判讀

下面這些判讀仍然值得保留：

- `dihedral_exponent = 1.0` 才是 canonical repaired AVL-first screening baseline
- `2.2` 不應再被當成 screening baseline 真值
- pre-fix regression 的主因不是 multiplier 方法壞掉，而是 baseline / gate contract drift
- 在 `exp = 1.0` 視窗內，higher multiplier 仍然呈現：
  - clearance 變大
  - trim AoA 略升
  - L/D 略降

所以真正被修正的，不是：

- 「multiplier 搜尋本身沒意義」

而是：

- **我們之前拿來排序 repaired shortlist 的 post-fix前提已經過時，現在必須改用這輪 current HEAD 的真實 full-gate結果。**

## 8. 最小必要驗證、風險、未完成處

### 最小必要驗證

- 已真實跑 `1` 輪 current HEAD full-gate bounded search
- 已覆蓋你要求的 `5` 個 multipliers
- 已確認 `5/5` 全部 full-gate pass
- 已留下完整 command / report / summary JSON artifact

### 主要風險

- 這個視窗雖然已經 full-gate clean pass，但 `aoa_trim_deg` 全部都略高於 telemetry `soft_trim_aoa_deg = 10.0`
- 所以 Track R 仍然應從較低 AoA 的 pass-side seed 開始，而不是直接跳去 `x4.25`

### 未完成處

- 這包沒有直接重跑 `Track R`
- 這包也沒有重跑 `candidate_rerun_vspaero`
- 這包只完成一件事：
  - 用修正後的真實結果，重建 repaired AVL-first canonical shortlist
  - 讓後續 `Track R` 不再用 stale seeds
