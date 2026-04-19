# Track Z — AVL Baseline Exponent Rebaseline Report

> 文件性質：真實 bounded compare / rebaseline report
> 任務日期：2026-04-19
> 任務目標：確認 repaired AVL-first path 的 canonical screening baseline 應回到 `dihedral_exponent = 1.0`，並把 `2.2` 降回 recovery / sensitivity 角色。

## 1. 結論

- **是，舊 AVL-first 主線的 canonical screening baseline 應回到 `dihedral_exponent = 1.0`。**
- 這次在同一組 repaired AVL structural seed、同一組 multiplier 視窗下做 apples-to-apples compare，結果很一致：
  - full-gate 下，`exp = 1.0` 與 `exp = 2.2` 都還是會先卡在 `trim_aoa_exceeds_limit`
  - 但 `exp = 1.0` 的 trim AoA 每個點都比 `2.2` 低一點，約 `0.005` 到 `0.008 deg`
  - `exp = 2.2` 的 L/D 只小幅較高，約 `0.07` 到 `0.12`
  - 真正大的差異出現在 structural follow-on：`exp = 1.0` 在 stability-only follow-on 下 **5/5 全部過線**，`exp = 2.2` 則 **5/5 全部 still fail `ground_clearance`**
- 所以這包真正回答的是：
  - `2.2` 沒有展現出足夠的 screening-side 優勢，不能繼續當 repaired AVL-first baseline
  - `2.2` 仍可保留，**但只合理地保留在 recovery / sensitivity**
    - 因為 Track T 已經證明它在 `candidate_rerun_vspaero` 的 heavy confirm path 上有 recovery 價值
    - 但那個價值不等於它應該回頭覆蓋舊 AVL-first screening baseline
- 基於 restored `exp = 1.0` baseline，我建議 Track R 的 canonical repaired shortlist 改成：
  - `x3.5`
  - `x3.75`
  - `x3.875`
  - `x4.0`（confirm-only，不建議當第一個 rib smoke）

## 2. 固定基準

這次 compare 固定沿用 Track X / Track T 已使用的 repaired AVL structural seed，只掃 exponent 與 multiplier：

- `aero_source_mode = candidate_avl_spanwise`
- `rib_zonewise_mode = off`
- multipliers / `target_shape_z_scale` window:
  - `3.5`
  - `3.75`
  - `3.875`
  - `4.0`
  - `4.25`
- fixed structural grids:
  - `main_plateau_grid = 1.0`
  - `main_taper_fill_grid = 0.999999500019976`
  - `rear_radius_grid = 0.9999997444012075`
  - `rear_outboard_grid = 1.0`
  - `wall_thickness_grid = 0.04630959736295326`
- compared exponents:
  - `dihedral_exponent = 1.0`
  - `dihedral_exponent = 2.2`

Track T 的既有 heavy confirm anchor 仍然保留，但角色要改正：

- `candidate_rerun_vspaero` + `exp = 2.2` 在 `3.75 < z_scale <= 3.875` 找到 first pass-side bracket
- 這是 **recovery evidence**
- 不是 repaired AVL-first screening baseline truth

## 3. 實際執行命令

### 3.1 full-gate repaired AVL-first bounded compare

以下命令各跑一次 `exp = 1.0` 與 `exp = 2.2`：

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --base-avl data/blackcat_004_full.avl \
  --output-dir /tmp/track_z_avl_exp<EXP>_fullgate_20260419 \
  --aero-source-mode candidate_avl_spanwise \
  --rib-zonewise-mode off \
  --multipliers 3.5,3.75,3.875,4.0,4.25 \
  --dihedral-exponent <EXP> \
  --main-plateau-grid 1.0 \
  --main-taper-fill-grid 0.999999500019976 \
  --rear-radius-grid 0.9999997444012075 \
  --rear-outboard-grid 1.0 \
  --wall-thickness-grid 0.04630959736295326 \
  --skip-local-refine \
  --skip-step-export \
  --cobyla-maxiter 160
```

### 3.2 stability-only repaired AVL structural follow-on

因為 3.1 的 `exp = 1.0` / `2.2` 都在 structural follow-on 前就被 `trim_aoa_exceeds_limit` 擋住，為了回答 screening baseline 到底該用誰，我補跑最小必要的 `--skip-aero-gates` compare：

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --design-report output/blackcat_004/ansys/crossval_report.txt \
  --base-avl data/blackcat_004_full.avl \
  --output-dir /tmp/track_z_avl_exp<EXP>_skipaero_20260419 \
  --aero-source-mode candidate_avl_spanwise \
  --rib-zonewise-mode off \
  --multipliers 3.5,3.75,3.875,4.0,4.25 \
  --dihedral-exponent <EXP> \
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

## 4. Bounded Compare Results

### 4.1 full-gate repaired AVL-first screening

| multiplier / `z_scale` | `dihedral_exponent` | trim AoA [deg] | L/D | `structure_status` | mass [kg] | clearance [mm] | reject reason |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| `3.5` | `1.0` | `12.48982` | `41.526` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `3.5` | `2.2` | `12.49499` | `41.598` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `3.75` | `1.0` | `12.50846` | `41.466` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `3.75` | `2.2` | `12.51463` | `41.554` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `3.875` | `1.0` | `12.51829` | `41.437` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `3.875` | `2.2` | `12.52495` | `41.533` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `4.0` | `1.0` | `12.52845` | `41.409` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `4.0` | `2.2` | `12.53560` | `41.513` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `4.25` | `1.0` | `12.54976` | `41.355` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |
| `4.25` | `2.2` | `12.55779` | `41.475` | `skipped` | `n/a` | `n/a` | `aero_performance:trim_aoa_exceeds_limit` |

判讀：

- full-gate 下沒有任何一個 exponent 在這個視窗內自己變成 clean pass-side winner
- 但 `exp = 1.0` 在每個 multiplier 上都：
  - trim AoA 略低於 `2.2`
  - reject reason 完全相同
- 所以 full-gate compare 並沒有提供任何理由把 `2.2` 升格成 baseline

### 4.2 stability-only repaired AVL structural follow-on

註：這張表的 trim AoA / L/D 是對應 full-gate 同一 multiplier 的 reference 值；`--skip-aero-gates` 的 summary 會把 aero performance 標成 skipped，所以這裡只是拿來做 apples-to-apples 對照，不把它冒充成 full-gate pass。

| multiplier / `z_scale` | `dihedral_exponent` | trim AoA ref [deg] | L/D ref | `structure_status` | mass [kg] | clearance [mm] | reject reason |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| `3.5` | `1.0` | `12.48982` | `41.526` | `feasible` | `21.740001` | `13.662` | `none` |
| `3.5` | `2.2` | `12.49499` | `41.598` | `infeasible` | `21.740001` | `-25.465` | `structural:ground_clearance` |
| `3.75` | `1.0` | `12.50846` | `41.466` | `feasible` | `21.740001` | `14.472` | `none` |
| `3.75` | `2.2` | `12.51463` | `41.554` | `infeasible` | `21.740001` | `-24.585` | `structural:ground_clearance` |
| `3.875` | `1.0` | `12.51829` | `41.437` | `feasible` | `21.740001` | `14.876` | `none` |
| `3.875` | `2.2` | `12.52495` | `41.533` | `infeasible` | `21.740001` | `-24.147` | `structural:ground_clearance` |
| `4.0` | `1.0` | `12.52845` | `41.409` | `feasible` | `21.740001` | `15.279` | `none` |
| `4.0` | `2.2` | `12.53560` | `41.513` | `infeasible` | `21.740001` | `-23.716` | `structural:ground_clearance` |
| `4.25` | `1.0` | `12.54976` | `41.355` | `feasible` | `21.740001` | `16.082` | `none` |
| `4.25` | `2.2` | `12.55779` | `41.475` | `infeasible` | `21.740001` | `-22.862` | `structural:ground_clearance` |

判讀：

- 這裡的主訊號非常強：
  - `exp = 1.0`：`5/5` 全部 structural feasible
  - `exp = 2.2`：`5/5` 全部 still fail `ground_clearance`
- mass 幾乎完全不變：
  - 全部都在 `21.740001 kg`
- screening-side 真正被 exponent 改變的不是 mass，而是 repaired AVL structural clearance

### 4.3 `exp = 1.0` 相對 `2.2` 的差異量級

| multiplier / `z_scale` | trim AoA delta [deg] | L/D delta | clearance delta [mm] |
| --- | ---: | ---: | ---: |
| `3.5` | `-0.00517` | `-0.072` | `+39.127` |
| `3.75` | `-0.00617` | `-0.088` | `+39.057` |
| `3.875` | `-0.00666` | `-0.096` | `+39.023` |
| `4.0` | `-0.00715` | `-0.104` | `+38.995` |
| `4.25` | `-0.00803` | `-0.120` | `+38.943` |

重點不是 `1.0` 在每個地方都「全面更好」，而是：

- `2.2` 的 screening-side 好處只剩很小的 L/D 提升
- 但代價是 repaired AVL structural clearance 大約少掉 `39 mm`
- 這個 tradeoff 明顯不適合再被稱為 canonical screening baseline

## 5. 直接回答這包的問題

### 5.1 repaired AVL-first path 下，`exp = 1.0` vs `2.2` 的差異到底有多大？

- 如果只看 full-gate aero screening：
  - 差異其實不大
  - 兩者都還是 `trim_aoa_exceeds_limit`
  - `1.0` 只有小幅較低的 trim AoA
  - `2.2` 只有小幅較高的 L/D
- 但如果把最小必要的 structural follow-on 補上：
  - 差異就非常大
  - `1.0` 是 `5/5` pass
  - `2.2` 是 `5/5` fail `ground_clearance`

所以這包真正把差異量級釘死的是：

- **aero gate 差異很小**
- **structural clearance 差異很大**

### 5.2 `2.2` 是否只能合理地留在 recovery / sensitivity，而不能當 screening baseline？

- **是。**

理由：

- 這次 repaired AVL-first bounded compare 沒有看到任何必須把 baseline 留在 `2.2` 的 screening-side 證據
- 相反地，現在看到的是：
  - `2.2` 沒有把 trim gate 救回來
  - `2.2` 卻把 repaired AVL structural clearance 整排拉回 fail-side
- 但 Track T 又已經證明：
  - 在 `candidate_rerun_vspaero` 的 heavy confirm / recovery path 中
  - `2.2` 確實可以是有價值的 clearance recovery heuristic

因此最合理的定位是：

- `exp = 1.0`：canonical AVL-first screening baseline
- `exp = 2.2`：recovery / sensitivity option

這裡最後一句是 **基於本次 bounded compare + Track T 已有 rerun evidence 的推論**，不是在宣稱 `2.2` 完全沒有價值。

### 5.3 在 `exp = 1.0` 基準下，後續真正該用的 repaired shortlist 是哪些 seeds？

我建議 canonical repaired shortlist 用 `4` 個 seeds：

- `x3.5`
- `x3.75`
- `x3.875`
- `x4.0`

而 `x4.25` 不進 shortlist，理由是：

- 相較 `x4.0` 只多大約 `0.803 mm` repaired AVL clearance
- 但 trim AoA 更高、L/D 更差
- 對第一輪 Track R smoke 來說，它帶來的新資訊不夠多

## 6. Canonical Repaired Shortlist

| Priority | multiplier / `z_scale` | `dihedral_exponent` | repaired AVL full-gate status | repaired AVL clearance [mm] | mass [kg] | why this seed matters | 下一步建議 |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| `1` | `3.5` | `1.0` | `stable` but `trim_aoa_exceeds_limit` | `13.662` | `21.740001` | restored baseline 下的 screening-side canonical winner：trim AoA 最低、L/D 最好，而且 repaired AVL structural follow-on 已經是 pass-side | **Track R 第一個 `off` vs `limited_zonewise` seed** |
| `2` | `3.75` | `1.0` | `stable` but `trim_aoa_exceeds_limit` | `14.472` | `21.740001` | 比 `x3.5` 多 `0.810 mm` clearance buffer，但只多 `0.01864 deg` trim AoA；是最自然的第二個 repaired baseline seed | **Track R 第二個 smoke seed** |
| `3` | `3.875` | `1.0` | `stable` but `trim_aoa_exceeds_limit` | `14.876` | `21.740001` | 接近舊 Track T pass-side bracket 的幾何尺度，但現在回到 `exp = 1.0` baseline；適合看 restored baseline 與舊 recovery bracket 之間的差距 | **Track R 第三個 / bridge seed** |
| `4` | `4.0` | `1.0` | `stable` but `trim_aoa_exceeds_limit` | `15.279` | `21.740001` | 有較大的 repaired AVL clearance buffer，也和舊 Track T confirm anchor 尺度接近；但它已開始明顯往更差的 trim / L/D 方向走，不適合當第一個 baseline smoke | **先做 confirm，不建議當第一個 rib smoke** |

### 為什麼 `x3.5` 要排第一個？

- restored baseline 的核心不是「誰 clearance 最大」而已
- 而是：
  - 在 repaired AVL-first screening baseline 下
  - 找出最早已經 structural pass-side
  - 同時 trim penalty 最小、L/D 保留最多的 seed
- 這個條件下，`x3.5` 最貼近 canonical baseline 的角色

### 為什麼 `x4.0` 只建議 confirm，不建議第一個 smoke？

- 它不是壞 seed
- 但對 restored baseline 來說，它比較像：
  - 帶較大 clearance buffer 的 confirm / backup seed
- 如果一開始就用它，會把：
  - restored baseline 的 screening truth
  - 和
  - 舊 recovery-side 的高 multiplier 習慣
  - 再次混在一起

## 7. 對 Track R 的明確建議

### 7.1 下一個 Track R 先用哪個 seed

- **先用 `x3.5` / `exp = 1.0`。**

### 7.2 第二個跑哪個 seed

- **第二個跑 `x3.75` / `exp = 1.0`。**

### 7.3 哪個 seed 只適合 confirm，不適合第一個 rib smoke

- **`x4.0` / `exp = 1.0`。**

如果 `x3.5` / `x3.75` 在 heavy confirm path 上又掉回 fail-side，再用 `x4.0` 看額外 clearance buffer 能不能把 smoke 拉回可比區間，比較符合 restored baseline 的節奏。

## 8. 最小必要驗證、風險、未完成處

### 最小必要驗證

- 真實跑了 `4` 輪 bounded compare：
  - `exp = 1.0` full-gate
  - `exp = 2.2` full-gate
  - `exp = 1.0` `--skip-aero-gates`
  - `exp = 2.2` `--skip-aero-gates`
- 總共 `20` 個真實 case
- 所有 run 都成功落出 summary CSV / JSON / report
- 輸出位置：
  - `/tmp/track_z_avl_exp1_fullgate_20260419/`
  - `/tmp/track_z_avl_exp22_fullgate_20260419/`
  - `/tmp/track_z_avl_exp1_skipaero_20260419/`
  - `/tmp/track_z_avl_exp22_skipaero_20260419/`

### 主要風險

- restored baseline 並不等於 repaired AVL-first full-gate 已經完全 clean
  - 這次 `exp = 1.0` 全部還是卡在 `trim_aoa_exceeds_limit`
- `exp = 1.0` 目前拿到的是 repaired AVL-first screening-side evidence
  - 不是 `candidate_rerun_vspaero` confirm-level truth
- 所以下一步仍然必須進 Track R
  - 不能把這份 report 誤讀成「Track R 已經不需要了」

### 未完成處

- 這一包**沒有**重跑 `candidate_rerun_vspaero` 的 `exp = 1.0` confirm compare
- 這一包**沒有**做 `off` vs `limited_zonewise`
- 這一包的價值是把：
  - baseline
  - recovery
  - repaired shortlist
  - 三者角色重新切正
