# Birdman 外翼 loading authority 診斷與低階介入掃描

- 分支：`birdman-fix-outer-loading-authority`
- 掃描腳本：[scripts/birdman_outer_loading_authority_sweep.py](../scripts/birdman_outer_loading_authority_sweep.py)
- 測試：[tests/test_birdman_outer_loading_authority_sweep.py](../tests/test_birdman_outer_loading_authority_sweep.py)
- AVL e sanity benchmark 仍通過：
  - `near_elliptic_uniform_airfoil`: e_CDi = 0.9937（>= 0.95）
  - `hpa_taper_uniform_airfoil`: e_CDi = 0.8935（>= 0.88）
  - 故 AVL Sref / Cref / Bref / paneling 契約沒有壞，問題出在 spanload / Ainc / chord 而非 AVL 本身

## 問題重述

> 為什麼 current Birdman inverse-chord mixed-airfoil candidate 的外翼 AVL
> circulation 只有 target 的約一半？要用 Ainc、chord、cl schedule 還是
> target loading repair 才能讓 eta 0.70～0.95 的 loading ratio 回到合理範圍？

## Baseline 重現

從中型 mission-coupled search 的最佳輸出讀回 sample 1476 的幾何（9 個翼站、
4 個 zone airfoil、span / area / a3 / a5），重新跑 AVL 並比對：

- 紀錄的 e_CDi：0.869533
- 重現的 e_CDi：0.869533（誤差 = 0.0）

外翼 AVL/target circulation_norm 比值：

| eta | target | AVL | ratio |
|---:|---:|---:|---:|
| 0.000 | 1.000 | 1.000 | 1.000 |
| 0.160 | 0.985 | 0.846 | 0.859 |
| 0.350 | 0.925 | 0.748 | 0.809 |
| 0.520 | 0.830 | 0.671 | 0.808 |
| 0.700 | 0.677 | 0.354 | 0.523 |
| 0.820 | 0.530 | 0.264 | 0.498 |
| 0.900 | 0.396 | 0.210 | 0.531 |
| 0.950 | 0.280 | 0.161 | 0.575 |

`outer_ratio_mean[0.70-0.95] = 0.532`，
`outer_ratio_min[0.80-0.92] = 0.498`，
brief 所說的 0.50～0.58 與此完全一致。

## 工程診斷

AVL 在 trim 時為了 CL_total 平衡會將 alpha 抬到根部過載
（root: target_cl=1.21, AVL_cl=1.51），代價是外翼欠載
（eta=0.82：target_cl=1.01, AVL_cl=0.66）。

可改變外翼 realised circulation 的低階自由度只有：

1. 外翼 Ainc / twist authority（提高有效 alpha）
2. 外翼 chord authority（增加同樣 cl 下的 circulation）
3. 外翼 airfoil camber / alpha_0L authority（這次不動）
4. 將 target 修得「比較好實現」（其實只動診斷分母）

我們直接做 1、2、4 三種介入，每個都重跑 AVL。

## 介入家族

| 家族 | 介入方式 | 是否守 area | 是否動 target | 守目前 gates |
|---|---|---:|---:|---|
| 外翼 Ainc bump | eta 0.65–0.98 平滑 cosine bump 加到 station.twist_deg | 是（不改 chord） | 否 | 部分（1.0 deg 內守、1.5 deg 起破） |
| 外翼 chord redistribution | eta 0.65–0.98 平滑 cosine bump 乘到 chord，並縮 inner chord 守 area | 是（解析守 area） | 否 | 全守 |
| Target outer taper | a3 更負、a5 略加，把 target 形狀往內推 | n/a | 是 | 守 |

掃描的 amplitude 範圍：
- Ainc: 0, +0.5, +1.0, +1.5, +2.0, +2.5 度
- Chord: 0, +10%, +20%, +30%, +40%
- Target taper fraction: 0, 0.30, 0.50, 0.70
- 額外一個低階組合：Ainc+1° 與 Chord+20%

## Sample 1476（mission 最佳）結果

| 介入 | knob | e_CDi | Δe | outer_mean[0.70–0.95] | outer_min[0.80–0.92] | gates |
|---|---:|---:|---:|---:|---:|---|
| Baseline | 0.00 | 0.8695 | 0.0000 | 0.532 | 0.498 | 全守 |
| Ainc +0.5° | 0.50 | 0.8777 | +0.008 | 0.547 | 0.520 | 全守 |
| Ainc +1.0° | 1.00 | 0.8854 | +0.016 | 0.562 | 0.543 | 全守 |
| Ainc +1.5° | 1.50 | 0.8927 | +0.023 | 0.577 | 0.565 | **outer_monotonic_washout 失敗** |
| Ainc +2.0° | 2.00 | 0.8996 | +0.030 | 0.593 | 0.588 | **outer_monotonic_washout 失敗** |
| Ainc +2.5° | 2.50 | 0.9060 | +0.036 | 0.609 | 0.611 | **outer_monotonic_washout 失敗** |
| Chord +10% | 0.10 | 0.8883 | +0.019 | 0.567 | 0.543 | 全守 |
| Chord +20% | 0.20 | 0.9057 | +0.036 | 0.602 | 0.589 | 全守 |
| Chord +30% | 0.30 | 0.9214 | +0.052 | 0.639 | 0.636 | 全守 |
| Chord +40% | 0.40 | 0.9353 | +0.066 | 0.677 | 0.684 | 全守 |
| Target taper 30% | 0.30 | 0.8695 | 0.000 | 0.561 | 0.526 | 全守 |
| Target taper 50% | 0.50 | 0.8695 | 0.000 | 0.581 | 0.546 | 全守 |
| Target taper 70% | 0.70 | 0.8695 | 0.000 | 0.602 | 0.566 | 全守 |
| Combined Ainc+1°+Chord+20% | combo | 0.9189 | +0.049 | 0.636 | 0.639 | 全守 |

JSON / station-level table 在
`output/birdman_outer_loading_authority_sweep_sample_1476/`。

## Sample 1383（最高 AR）結果

| 介入 | knob | e_CDi | Δe | outer_mean[0.70–0.95] | outer_min[0.80–0.92] | gates |
|---|---:|---:|---:|---:|---:|---|
| Baseline | 0.00 | 0.8591 | 0.0000 | 0.511 | 0.487 | 全守 |
| Ainc +1.0° | 1.00 | 0.8773 | +0.018 | 0.543 | 0.536 | 全守 |
| Ainc +1.5° | 1.50 | 0.8858 | +0.027 | 0.559 | 0.559 | **outer_monotonic_washout 失敗** |
| Chord +20% | 0.20 | 0.8985 | +0.039 | 0.582 | 0.577 | 全守 |
| Chord +40% | 0.40 | 0.9325 | +0.073 | 0.658 | 0.669 | 全守（root_chord = 1.056 m，貼著 1.05 下限） |
| Combined Ainc+1°+Chord+20% | combo | 0.9146 | +0.055 | 0.617 | 0.627 | 全守 |

兩個 candidate 排序一致：chord > Ainc（受 gate 限）>> target。詳見
`output/birdman_outer_loading_authority_sweep_sample_1383/`。

## 問題回答

1. **AVL contract 沒壞。** 外翼欠載的成因是 inner-overloading 幾何與外翼
   chord×camber 不夠對應 target，AVL 的 trim 平衡只能透過抬 alpha 解決，
   但這會把根部推得更高、外翼更低。
2. **目前最強的單一 within-gate 槓桿是外翼 chord redistribution。**
   平滑 cosine bump（peak eta=0.85，eta=0.65–0.98）+20% 即可在所有 gates
   合格的情況下將 e_CDi 從 0.870 推到 0.906（sample 1476）或 0.859 推到
   0.899（sample 1383）。+40% 可以再推到 0.93–0.94，但 sample 1383 的
   root_chord 已貼著 1.05 m 下限，建議搜尋上限放在 +30%。
3. **外翼 Ainc bump 的 raw authority 與 chord 接近，但目前被
   `outer_monotonic_washout` gate 鎖在 +1.0 度以內。** 進一步放寬會破
   gate；要把 +1.5 度以上的 bump 變合法，必須把 outer monotonic 規則改成
   「允許形狀受限的 smooth bump」，並寫入 gate 例外。
4. **Target outer taper 不會改變 AVL realised e_CDi。** 它只能讓
   diagnostic 比值好看，所以**不能用來掩蓋 underloaded**；只在 target
   本身真的物理不可實現時才考慮使用。
5. **這個結論在兩個 candidate 上一致**（mission-best 與 highest-AR），
   不是 sample-1476-only 的偶然。

## 為什麼 target loading 不是當下瓶頸

sample 1476 的 target Fourier 形狀是
`a3_over_a1 = -0.028, a5_over_a1 = -0.001`，
`target_fourier_e = 0.998`、`outer_loading_ratio_eta_0p90 = 0.934`，已落在
`spanload_design.outer_loading_eta_0p90_max_ratio_to_ellipse = 0.95` 限制
之內。eta=0.70 的 target_cl 約 1.22，相對 `local_clmax_safe_floor = 1.65`
利用率約 0.74，外翼還有 cruise CL margin。AVL 實際 cl 在 eta=0.70 只有
0.83，遠低於 outer cruise CL 的 1.24 limit。**外翼 cl headroom 足夠**，問
題只是「沒被要求做 cl」，不是「不能做 cl」。

## 下一步：開哪個自由度？

### 1. 先開 chord（最快也最低風險）

把 outer-chord-bump 的 amplitude 加進現有 inverse-chord stage-1 pipeline，
作為一個低階搜尋變數，bound 在 `[0, 0.30]`，這樣即使最差情況下 root_chord
仍守 `>= 1.05` m。

理由：
- 動的位置 brief 已經要求（eta = 0.70–0.95）
- 建構上守 area，跟 inverse-chord 直接相容
- 守目前所有 gates（twist、tip、local CL、Fourier ratio）
- 單一 scalar，optimizer 負擔極小
- 預估 e_CDi gain 約 +0.03 ~ +0.05

### 2. 接著開 Ainc（必須先動 gate 規則）

目前的 outer monotonic washout 規則對標 HPA 純 twist wing，diagnostic
證實它已成為 Ainc authority 的瓶頸。建議的 gate 修改：

- 允許形狀與振幅受限的 smooth cosine bump（peak eta=0.85，eta=0.65–0.98，
  |amplitude| <= 1.5 度）
- eta < 0.45 的 twist 仍須守原規則
- gate 修改要明文寫成「Birdman P1 outer Ainc authority bump 例外」

放寬後加上 chord redistribution，e_CDi 應該可以穩定 >= 0.92。

### 3. 暫時不動 airfoil 與 target loading

- airfoil（CST/XFOIL）：sanity benchmark 已證明 e=0.99 是可達的，airfoil
  本身不是瓶頸；要動也應該等 planform / Ainc levers 用盡
- target loading repair：目前只會改診斷分母，不能解決 realised loading

## Mission verdict 注意

sample 1476 的 max_range proxy 為 8.6 km、sample 1383 為 12.6 km，仍是
fixed-profile-drag proxy；**這次掃描不能用來宣稱 42.195 km 完賽**。e_CDi
往上 0.04~0.07 對 induced drag 有幫助，但 profile drag 的最終值還在等
CST / XFOIL pipeline。

## 對應 brief 的 acceptance

| 條件 | 狀態 |
|---|---|
| sanity benchmark 不退化 | 守住（0.9937 / 0.8935） |
| diagnostic 清楚顯示 underload 位置與量 | 守住（4 個 outer eta 樣本 + 兩個窗 metric） |
| 至少一個 controlled intervention | 三個：Ainc、chord、target taper |
| 新候選改善至少一個 metric | 全部四個都改善（e、mean、min、Δe） |
| accepted candidate e_CDi >= 0.88 且 gates 合格 | chord +10% 已達 e=0.888 全 gates 合格；chord +40% 達 e=0.935 |
| 不宣稱 42.195 km 可完賽 | 不宣稱（仍是 proxy） |

## 跑出來的工件

- `scripts/birdman_outer_loading_authority_sweep.py`
- `tests/test_birdman_outer_loading_authority_sweep.py`
- `output/birdman_avl_e_sanity_benchmark_baseline/avl_e_sanity_benchmark.{json,md}`
- `output/birdman_outer_loading_authority_sweep_sample_1476/{outer_loading_authority_sweep.json, outer_loading_authority_sweep.md, engineering_report.md}`
- `output/birdman_outer_loading_authority_sweep_sample_1383/{outer_loading_authority_sweep.json, outer_loading_authority_sweep.md}`
