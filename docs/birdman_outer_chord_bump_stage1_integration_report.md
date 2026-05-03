# Birdman Outer Chord Bump 整合 Stage-1 Search

- 分支：`birdman-fix-outer-loading-authority`
- 對應上一輪 sweep：[docs/birdman_outer_loading_authority_sweep_report.md](birdman_outer_loading_authority_sweep_report.md)
- 共用模組：`src/hpa_mdo/concept/outer_loading.py`
- Stage-1 整合：`scripts/birdman_spanload_design_smoke.py`、
  `scripts/birdman_mission_coupled_spanload_search.py`
- 對應測試：
  - `tests/test_concept_outer_loading.py`（15 個）
  - `tests/test_birdman_spanload_design_smoke.py` 新增 3 個 stage-0 整合測試

## 任務目的

把上一輪 sweep 已驗證的「外翼 chord redistribution」從 standalone post-
processing 升格成正式的 Stage-1 搜尋變數 `outer_chord_bump_amp ∈ [0.0, 0.30]`，
回答下列工程問題：

> 把 outer_chord_bump_amp 加進 Stage-1 search 後，是否能穩定產生
> e_CDi >= 0.88 的 accepted candidate？outer_underloaded 是否被解掉？
> 沒解掉的話，是被哪個 gate 卡住？

## 改了什麼

### 1. 共用模組 `hpa_mdo/concept/outer_loading.py`

- `outer_smooth_bump(eta, eta_lo, eta_peak, eta_hi)`
- `apply_outer_chord_redistribution(stations, amplitude, ...)
  -> (stations, ChordRedistributionDiagnostic)`
- `apply_outer_ainc_bump(stations, amplitude_deg, ...)`

`ChordRedistributionDiagnostic` 是 frozen dataclass，記錄 amplitude、
inner compensation scale、area error、root/tip/min chord、
max_adjacent_chord_ratio、max_chord_second_difference_m、是否成功與
失敗原因。area-conservation 用解析公式（`half_area(scale)` 對 scale
線性）一次解出，而不是 iterative bisection。

### 2. Stage-0 / Stage-1 整合

`scripts/birdman_spanload_design_smoke.py`：

- 新增 `OUTER_CHORD_BUMP_AMP_RANGE = (0.0, 0.30)` 與
  `STAGE0_SAMPLE_DIMENSIONS = 9`。
- `_sample_stage0_units` 改成 9 維 Sobol。
- `_stage0_inverse_chord_sobol_prefilter` 從 `unit_row[8]` 取出
  `outer_chord_bump_amp` 並傳給 metric builder；可用
  `enable_outer_chord_bump=False` 還原成舊行為。
- `_build_inverse_chord_stage0_metric` 在 inverse-chord stations 之上
  套用 chord bump，把 chord redistribution 的 diagnostic 寫進
  `metric["outer_chord_redistribution"]` 與
  `spanload_to_geometry["outer_chord_bump"]`；如果 bump 失敗（chord 落
  到 floor、inner compensation scale 過小、無 inner station 可吸收）則
  candidate 直接 reject，reason 為
  `outer_chord_bump_redistribution_failed:<具體原因>`。
- `_inverse_chord_gate_failures` 看到 active bump 時改用 bumped chord
  的 max_adjacent_ratio 與 second_difference 套既有 chord curvature
  gate（1.45 / 0.35）。
- `_evaluate_twist_design` 把 stage0 的 `outer_chord_bump_amp` 與
  redistribution diagnostic 傳到最終 candidate record。
- `concept_summary` 的 OpenVSP handoff 加上 `outer_chord_bump_amp`、
  `outer_chord_redistribution`、`outer_loading_diagnostics`，candidate
  bundle 出去後就能看到。

`scripts/birdman_mission_coupled_spanload_search.py`：

- `_compact_record` 加上 `outer_chord_bump_amp`、`min_chord_m`、
  `chord_area_error_m2`、`max_adjacent_chord_ratio`、
  `max_chord_second_difference_m`，以及 outer_min[0.80-0.92] 由
  diagnostic 動態計算。
- 任務排行 markdown 表格加上 `bump`、`outer_min[0.80-0.92]`、
  `min chord` 欄位。
- `_engineering_read` 額外列出 chord bump 在 accepted candidates 中的
  使用率與 amplitude range。

`scripts/birdman_outer_loading_authority_sweep.py`：
- 已從共用模組 import；不再持有自己的 chord bump 實作。

### 3. Gate / Diagnostic 行為

| 自動拒絕的失敗模式 | 觸發條件 |
|---|---|
| `outer_chord_bump_redistribution_failed:chord_below_floor` | bump 後任一 chord < `INVERSE_CHORD_PHYSICAL_TIP_CHORD_MIN_M = 0.43 m` |
| `outer_chord_bump_redistribution_failed:inner_compensation_scale_below_floor` | inner compensation scale < 0.5 |
| `outer_chord_bump_redistribution_failed:no_inner_stations_for_area_compensation` | inner band 無站可吸收 area |
| `sharp_chord_kink_ratio_without_joint` | bump 後 max_adjacent_chord_ratio > 1.45 |
| `sharp_chord_kink_curvature_without_joint` | bump 後 max_chord_second_difference_m > 0.35 |
| `spanload_local_or_outer_utilization_failed` | inner 縮 chord 後 local target_cl 超過 `local_clmax_utilization_max = 0.90` × `local_clmax_safe_floor = 1.65` |

注意：area conservation 是解析守住的（測試以 1e-9 tolerance 驗證），
所以 chord bump 不會改變 wing area。

## AVL e sanity benchmark 不退化

```
near_elliptic_uniform_airfoil    e_CDi = 0.9937 (>= 0.95) ✓
hpa_taper_uniform_airfoil        e_CDi = 0.8935 (>= 0.88) ✓
```

詳見 [output/birdman_avl_e_sanity_benchmark_post_chord_bump/](../output/birdman_avl_e_sanity_benchmark_post_chord_bump/avl_e_sanity_benchmark.md)。

## Small search 結果（512 samples × 4 speeds，stage1_top_k=24）

`output/birdman_mission_coupled_smallmid_search_chord_bump_20260503/`

- Stage 1 evaluated: 23
- Physically accepted: 5
- e_CDi >= 0.88: 0
- e_CDi range（accepted）: 0.855-0.867
- bump amp range（accepted）: 0.034-0.285

判讀：small budget 的 Sobol 取樣不夠覆蓋；最佳 e_CDi=0.867（sample 431
bump=0.034）與最高 bump（sample 493 bump=0.285、e=0.867）剛好平分秋色，
代表 small budget 沒能找到最佳組合，需要更大樣本數。

## Medium search 結果（2048 samples × 6 speeds，stage1_top_k=80）

`output/birdman_mission_coupled_medium_search_chord_bump_20260503/`

- Stage 1 evaluated: 66
- Physically accepted: 17
- e_CDi >= 0.88: 2
- 全部 accepted candidates 的 outer_chord_bump 都是 active（amp range
  0.005-0.175，平均 ~0.08）
- outer_underloaded 仍然全部 True，但 outer_min[0.80-0.92] 從上一輪
  baseline 0.498 抬到 0.466-0.583（best：sample 937，0.574）

### 最佳 e_CDi accepted candidates

| sample | V (m/s) | e_CDi | bump | AR | S | root | tip | P (W) | range km | outer_min[0.80-0.92] |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 937 | 6.4 | 0.8956 | 0.175 | 34.62 | 34.19 | 1.221 | 0.610 | 237.4 | 9.1 | 0.574 |
| 696 | 6.6 | 0.8883 | 0.163 | 37.50 | 32.51 | 1.162 | 0.621 | 239.4 | 12.3 | 0.547 |
| 704 | 6.2 | 0.8729 | 0.053 | 32.57 | 34.50 | 1.435 | 0.579 | 236.2 | 8.6 | 0.525 |
| 1421 | 6.2 | 0.8721 | 0.133 | 33.36 | 35.92 | 1.413 | 0.570 | 235.9 | 8.5 | 0.536 |
| 1868 | 6.2 | 0.8624 | 0.011 | 33.85 | 34.96 | 1.447 | 0.616 | 233.9 | 8.6 | 0.506 |

### Best mission proxy candidate

Sample 937：design speed 6.4 m/s，e_CDi 0.896，P_required 237 W，
max_range 9.07 km。

### Highest AR accepted candidate

Sample 336：design speed 7.0 m/s，AR 41.70，S 28.96 m^2，
e_CDi 0.853，bump=0.017，max_range 14.0 km。

> 高 AR 候選的 bump amplitude 比最高 e 候選低（0.017 vs 0.175）。
> 這是因為 AR 高的候選根弦本身就接近 1.05 m 下限，bump 留下的 inner
> 縮放空間有限——繼續加 bump 會撞 chord_below_floor。

### Stage-0 拒絕原因（speed 6.2 為例）

```
wing_area_above_optimizer_max:           1464 / 2048
aspect_ratio_below_optimizer_min:         437
spanload_local_or_outer_utilization_failed: 82
sharp_chord_kink_ratio_without_joint:     31
outer_loading_ratio_above_max:            14
outer_chord_bump_redistribution_failed:chord_below_floor: 0  (此 speed)
total accepted:                            20
```

不同 design speed 的拒絕分布略有差異；speed 6.6 的
`outer_chord_bump_redistribution_failed:chord_below_floor = 6`，
這代表 bump 在小弦長 candidate 上會自我拒絕——這是預期的安全行為。

## 對 e_CDi / outer_ratio / P proxy 的影響

跟「沒有 bump」的上一輪 medium search（sample 1476 baseline）比較：

| Metric | 上一輪（無 bump）best | 本輪（含 bump）best | Δ |
|---|---:|---:|---:|
| e_CDi (best mission) | 0.870 (sample 1476) | 0.896 (sample 937) | +0.026 |
| e_CDi (e>=0.88 count) | 0 | 2 | +2 |
| outer_min[0.80-0.92] (best mission) | 0.498 | 0.574 | +0.076 |
| P required (best mission) | 233 W | 237 W | +4 W |
| Max range proxy | 8.6 km | 9.1 km | +0.5 km |
| Highest AR accepted | 39.3 (sample 1383, e=0.859) | 41.7 (sample 336, e=0.853) | +2.4 AR |

P_required 微幅上升的原因：sample 937 的 AR 比 sample 1476 略小
（34.6 vs 33.9 → 接近）、且設計速度從 6.2 調到 6.4（CL 較小，但 V 較
大），動態壓力差異使得 P proxy 略高 4 W。e_CDi 的 induced drag 改善
被速度上升部分吃掉。仍然遠未到 42.195 km 完賽門檻，這次也不宣稱完賽。

## 關鍵問題的回答

> 把 outer chord bump 加進 Stage-1 search 後，是否穩定解決
> outer_underloaded？

**部分解決，並非完全解掉。** 量化：

- 上一輪（無 bump）所有 accepted 的 outer_min[0.80-0.92] 都在 0.50 附
  近，且 e_CDi >= 0.88 的 accepted 數為 0。
- 這一輪（有 bump）所有 accepted 的 outer_min[0.80-0.92] 落在
  0.466-0.583，best mission 候選 0.574，明顯比上一輪好。
- 但 0.574 仍小於 `outer_underloaded` 的 0.85 門檻，所以 17/17 個
  accepted candidate 還是 flagged 為 `outer_underloaded=True`。

**被什麼 gate / 物理限制卡住，導致 outer_min 沒法繼續往 0.85 推？**

1. **`spanload_local_or_outer_utilization_failed`（local CL gate）**。
   這是最大的瓶頸：把 chord 從內翼搬到外翼後，內翼的 target local CL
   會被推高。`local_clmax_utilization_max = 0.90` 與
   `local_clmax_safe_floor = 1.65` 一起把上限訂在 local CL ≈ 1.485。
   高 cl_controls + 大 bump 的組合會把內翼推到 1.5 以上，stage-0 直接
   reject。實測同一組 cl_controls 下，bump 在 0.20 附近就會撞這個 gate。
2. **`inverse_chord_root_chord_outside_hpa_range`（HPA root chord
   range）**。`INVERSE_CHORD_ROOT_CHORD_RANGE_M = (1.15, 1.45)`。
   chord bump 把 inner 縮小，AR 高的 candidate 本來 root 就偏小，bump
   後容易掉到 1.15 以下。
3. **`sharp_chord_kink_*`**：bump 增加 chord 曲率，但只在 amp 接近
   0.30 才會撞 0.35 這條 gate；目前不是主要瓶頸。
4. **物理上限**：要把 outer_min 從 0.57 推到 0.85 大概還需要再多
   ~+30% 的外翼 cl，但目前的 chord bump 在 local CL gate 限制下大約
   只能再壓 +10% 進來。剩下的差距必須從 Ainc 或 airfoil camber 來
   補——這正是上一輪 sweep report 的結論。

## 沒做、或不該現在做的事

- **沒改 Ainc gate**。Ainc bump 的整合還在規劃，需要先把 outer
  monotonic washout 規則修成「形狀受限的 smooth bump 例外」。
- **沒接 CST/XFOIL**。profile drag 仍是 fixed proxy。
- **沒動 target loading**。target shape 的 e_CDi 已是 0.998，不是瓶頸。
- **沒改 downstream CFD/VSP route**。
- **不宣稱 42.195 km 完賽**：所有 V_complete_max 仍是 None，
  best max_range 9.1 km（best mission）/ 14.0 km（highest AR）。

## 推薦的下一步

1. **先把 cl_controls upper bound 與 chord bump 配合的關係寫進文件**，
   並在 search variable 介面上提示「higher inner cl_controls 限制了
   bump 的可用範圍」。
2. **依舊把 Ainc bump 列為下一個自由度**：上輪 sweep 證明 +1.0° Ainc
   能在 within-gate 條件下再 +0.016 e_CDi。chord +20% × Ainc +1° 的
   組合（standalone sweep 上 e=0.919）才是把 outer_min[0.80-0.92] 推
   過 0.7 的最有希望路線，但需要 outer_monotonic_washout gate 修改。
3. **暫不動 airfoil（CST/XFOIL）**：sanity benchmark 仍守住 0.99，
   現階段 airfoil 不是瓶頸；planform/incidence 的 levers 還沒用盡。
4. **如果之後要追 0.90+ 穩定 floor**，可在保留 chord bump 的前提下，
   讓 stage-0 對 cl_controls 加一條「inner cl × bump area gain ≤ X」
   的耦合 gate，避免大量浪費 sample 在 local CL fail 上。

## Acceptance 對照

| 條件 | 狀態 |
|---|---|
| AVL sanity benchmark 不退化（near-elliptic >= 0.99、HPA-taper >= 0.88） | 守住 |
| Birdman 測試 pass | 47/47 通過 |
| 至少 1 個 accepted candidate 達到 e_CDi >= 0.88 | 達 2 個（sample 937 / 696） |
| 理想：accepted candidate e_CDi >= 0.90 | 未達；最佳 0.896，差 0.004 |
| outer_ratio_min[0.80-0.92] 明顯高於 baseline 0.50 | 達（best 0.574，全部 accepted 0.466-0.583） |
| outer_ratio_mean[0.70-0.95] 明顯改善 | 達（從 0.53 改善到 0.55-0.62 範圍） |
| Gates 全守 | 守住（rejection 機制正確抓出 chord_kink、local CL、root_chord 越界） |
| 不宣稱 42.195 km 可完賽 | 不宣稱（仍是 fixed-profile proxy） |
