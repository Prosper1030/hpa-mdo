# Birdman MIT-like Cruise-Aware Twist Oracle 報告

- 分支：`birdman-fix-outer-loading-authority`
- 對應前一輪：[docs/birdman_mit_like_closed_loop_redirect_report.md](birdman_mit_like_closed_loop_redirect_report.md)
- 目的：在 **MIT-like 高 AR / 合理 taper / 不允許 outer chord bump**
  的 fixed-planform 上，跑 cruise-aware 4-DOF twist 優化，
  測量 no-airfoil 上限 e_CDi、外翼比、local CL 等等，
  回答「MIT-like planform 是否可行」。

## 改了什麼

### 1. 共用模組 `hpa_mdo/concept/cruise_twist_oracle.py`

新檔（[原始檔](../src/hpa_mdo/concept/cruise_twist_oracle.py)）：

- `TwistVector(root_incidence_deg, linear_washout_deg,
  outer_bump_amp_deg, tip_correction_deg)` — 4 自由度，brief 列的
  「root incidence + linear washout + smooth mid-outer Ainc bump +
  tip washout correction」一一對應。
- `twist_at_eta(twist, eta)` 公式：
  `α(eta) = root_inc + linear_washout × eta
            + outer_bump_amp × outer_smooth_bump(eta)
            + tip_correction × eta³`
  smooth bump 重用前輪驗證過的
  `hpa_mdo.concept.outer_loading.outer_smooth_bump`，eta 0.65–0.98。
- `optimize_twist_for_candidate(...)`：
  - 用 5 個 seed twist + scipy Powell（maxfev、maxiter 由 caller 控）
  - 每次 evaluation 跑 AVL no-airfoil trim + spanwise（直接呼叫
    `_run_avl_trim_case` / `_run_avl_spanwise_case`），不走全部
    design cases，速度更快。
  - 目標函數：
    - `cd_induced` × 200
    - outer_ratio penalty（`max(0, 0.85 − ratio_min)²`）× 30
    - target spanload match RMS² × 8
    - 4-DOF twist amplitude 平方 smoothness × 0.2
    - twist physical gate 失敗 × 5
    - local_cl_max_utilization 超 0.90 的平方 × 50
  - 硬 gate（直接 reject 候選）：
    - twist range > 7°、max_abs > 6°、adjacent_jump > 2°、
      outer_wash_in_step > 0.6° → twist physical gate fail
    - tip gate fail
    - AVL trim 不收斂

### 2. CLI script `scripts/birdman_mit_like_twist_oracle.py`

新檔：對每個 MIT-like candidate 執行
1. 用 `generate_mit_like_candidates`（AR 37–40 / taper 0.30–0.40）
   產生 candidate（**不疊任何外翼 chord bump**）。
2. 在 cruise CL_required = m·g/(q·S) 下建出 Fourier target spanload
   （a3=−0.05, a5=0.0），給每個 station 一個
   `target_circulation_norm` / `target_local_cl`。
3. 呼叫 oracle，取得最佳 twist + e_CDi / outer_ratio /
   local_cl_util / twist gate 結果。
4. 分類：
   - `e_cdi_ge_0p88_primary` → planform 可行
   - `e_cdi_0p85_to_0p88_diagnostic` → 邊際
   - `e_cdi_below_0p85` → 卡住，記錄 driver
5. 為每個 e_CDi < 0.85 的候選列出 driver
   （local_cl_above_safe_utilisation /
    outer_loading_below_target_floor /
    target_match_max_delta_above_30pct /
    twist_gate:*）。

不再算任何 mission power proxy（brief 明令不要把 143 W 當 final）。

### 3. 測試

新檔 [tests/test_concept_cruise_twist_oracle.py](../tests/test_concept_cruise_twist_oracle.py)：
10 個純函式測試覆蓋 twist parameterisation、smoothness、smooth bump
support、outer ratio window 容差、target match RMS、twist 物理 gate
判斷、4-DOF bound 完整性。

## Validation 結果

### AVL sanity benchmark 不退化

`output/birdman_avl_e_sanity_benchmark_post_twist_oracle/`：
- `near_elliptic_uniform_airfoil`: e_CDi = **0.9937** (≥ 0.95) ✓
- `hpa_taper_uniform_airfoil`: e_CDi = **0.8935** (≥ 0.88) ✓

### 16-candidate 完整 oracle pass（cruise 6.6 m/s）

`output/birdman_mit_like_twist_oracle_validation/mit_like_twist_oracle_report.json`

- 14 個 candidate 進入閉環（2 個被 generator hard constraint 拒絕）
- **classification: 14/14 落在 `e_cdi_below_0p85`**
- 沒有 candidate 達到 `e_cdi_0p85_to_0p88_diagnostic` 或更高
- e_CDi 範圍 0.66–0.82，best：sample 11 e=0.8195

### Top 5 best e_CDi candidates

| rank | sample | AR | taper | S | CL_req | aoa | e_CDi | outer_min[0.80-0.92] | local_cl_util |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 11 | 38.77 | 0.387 | 26.65 | 1.465 | 4.66 | 0.8195 | 0.622 | 1.051 |
| 2 |  2 | 37.36 | 0.396 | 29.13 | 1.341 | 4.52 | 0.8019 | 0.592 | 0.975 |
| 3 | 14 | 37.72 | 0.363 | 28.22 | 1.384 | 4.72 | 0.7977 | 0.580 | 0.997 |
| 4 | 15 | 39.28 | 0.344 | 27.61 | 1.415 | 4.84 | 0.7937 | 0.572 | 1.014 |
| 5 |  6 | 37.87 | 0.334 | 27.51 | 1.420 | 4.85 | 0.7928 | 0.569 | 1.015 |

### Driver 分布（14 個候選）

```
outer_loading_below_target_floor:        14 / 14
target_match_max_delta_above_30pct:      14 / 14
local_cl_above_safe_utilisation:         13 / 14
```

**幾乎所有候選都 同時被三個 driver 卡住**。

## 工程診斷（明確答案）

### 結論：MIT-like fixed-planform + 4-DOF twist 在目前的物理 envelope 下，無法達到 e_CDi ≥ 0.85，更別說 0.88-0.92。上限是 **e_CDi ≈ 0.82**，blocker 是 **local CL 在根部達到 safe_clmax 的限制**。

### Driver 1（主因）：cruise CL 太高 → root local CL 撞到 safe limit

- Birdman 設計總質量 98.5 kg，cruise 6.6 m/s
- MIT-like span_range_m = (32, 35) × ar_range = (37, 40) 鎖死 mean
  chord 在 0.80-0.95 m，wing area 落在 26-33 m²
- W/S = 30-37 N/m²，CL_required = 1.20-1.50
- AVL 在 CL_req=1.30-1.50 trim 時，α ≈ 4-5°，**根部 local CL = 1.40-1.50**，已撞到
  `local_clmax_safe_floor × local_clmax_utilization_max = 1.65 × 0.90 = 1.485`
- 13/14 個候選都觸發 `local_cl_above_safe_utilisation`

### Driver 2：target spanload 不可實現

- target Fourier shape (a3=−0.05) 是 near-elliptic
- 在 CL_req = 1.30+ 下，要實現 near-elliptic 必須
  `outer cl ≈ 1.0`，`root cl ≈ 1.5`
- 14/14 個候選 `outer_loading_below_target_floor`：外翼 ratio
  落在 0.41–0.62，全部低於 0.85 floor
- 14/14 個候選 `target_match_max_delta_above_30pct`：
  最差站 spanload normalised 差異 > 30%

### Driver 3：4-DOF twist parameterization 是受限的，但**不是主因**

- Powell 收斂到 `linear_washout ≈ −0.03°`、`outer_bump_amp ≈ 1.20°`、
  `root_incidence ≈ −1.0°`、`tip_correction ≈ 0`：
  - outer bump 是用滿了（接近 1.5° 上限的 80%）
  - linear washout 反而是接近 0（因為 washout 越強，root local CL 抬越高，
    撞 local CL gate）
- 沒有任何候選觸發 `twist_gate_failure`，所以 twist gate 不是 binder
- 4-DOF 的限制其實是 **AVL trim 的 root-balance 物理**：
  增加 outer Ainc 會逼 trim α 下降，整體 CL 也下降，
  必須再抬 root incidence 才能維持 CL_req → root local CL 又升上來

### Driver 4：MIT-like generator 的 wing area 和 span 上限

- 要把 cruise CL 拉到 ≤ 1.0，需要 wing area ≥ 38 m² 或 span 加到 38 m
- 在 AR 37-40 的拘束下：
  - S=38, AR=37 → span = √(37·38) ≈ 37.5 m → 比 brief 隱含的 35 m 上限大
  - S=38, AR=40 → span ≈ 39 m → 同上
- 換句話說，**「AR 37-40 + span ≤ 35 m + 98.5 kg」這三個條件本身是
  over-constrained 的 HPA 物理 envelope**

## 「是 taper、target spanload、tip gate、local CL gate 還是 spanload mapping 問題」

| 候選 driver | 是不是這次的 binder？ |
|---|---|
| **local CL gate** | **是**（13/14 撞，主 binder） |
| **target spanload** | **是**（14/14 不能實現 a3=−0.05） |
| **wing-area / W·S 物理上限** | **是**（直接造成 CL_req 太高） |
| taper | 不是（0.30-0.40 範圍掃過，沒有顯著差異） |
| tip gate | 不是（0/14 撞 tip gate） |
| spanload mapping (Fourier→station) | 不是（target_records 計算正確；map 到 trapezoidal stations 有效；rms_delta 在 0.15-0.20 範圍） |

## 建議的下一步（按工程優先序）

> 重要：以下都是工程選擇，**brief 不允許退回 outer chord bump 或放棄 AR 37-40**，所以下列選項都在 MIT-like 框架內：

### 選項 A：解 cruise CL 過高（推薦）

1. **允許 span > 35 m 或允許 wing area > 33 m²**：
   把 `DEFAULT_SPAN_RANGE_M` 從 (32, 35) 放寬到 (32, 38)，配合
   AR 37-40 → wing area 可達 38 m²，cruise CL ≈ 0.95-1.10。
2. **降低 cruise speed 到 ~6.0 m/s**：cruise speed 越慢，CL 越高，
   反向；不行。
3. **加快 cruise 到 ~7.5-8.0 m/s**：實測 7.5 m/s 反而 e_CDi 下降到
   0.68-0.72（因為 local cl 仍接近 safe limit，且 4-DOF twist
   沒有跟著重新最佳化）。需要更多 budget，但物理上仍然是 W/S 主導。

### 選項 B：把 CST/XFOIL search 接入

- 替 root/mid1 zone 找 `clmax_safe_floor > 1.65` 的 cambered airfoil
- 把 `local_clmax_utilization_max` 釋放到 0.95（限制要明寫）
- 這正是 brief 規劃的下一階段；oracle 已證明 **planform** 不是
  瓶頸（AVL trim 出來的 cl 分布很合理），瓶頸是 **section CLmax**

### 選項 C：把 target spanload 由 a3=−0.05 改為 a3=−0.03（更內偏）

- 較內偏的 target 自然降低外翼 cl_target 要求
- 風險：違背 MIT-like 設計初衷（outer ellipse-like loading）
- 不建議在不接 CST/XFOIL 之前就先動 target

## 不能/不該宣稱的事

- **不能** 宣稱 MIT-like + 4-DOF twist 已可飛
- **不能** 宣稱 mission power 的最終值（profile drag 還是 fixed proxy）
- **不要** 把 143 W 當作 cruise power 上限（brief 明令）
- **不要** 退回 outer chord bump（brief 明令）
- **不要** 放棄 AR 37-40（brief 明令）

## Acceptance 對照

| 條件 | 狀態 |
|---|---|
| 用 generate_mit_like_candidates 產生 AR 37-40 / taper 0.30-0.40 | 達成 |
| 不允許 outer chord bump | 達成（generator + oracle 完全沒有 chord 自由度） |
| 加入 root incidence + linear washout + outer bump + tip correction 的 4-DOF twist | 達成 |
| 在 cruise CL_req 跑 AVL，目標不是單純 maximize e | 達成（CDi + outer_ratio + match + smooth + gate penalty） |
| 輸出 best e_CDi、outer_min[0.80-0.92]、twist distribution、local CL margin、rejected reason | 達成（全部都在 JSON / Markdown 報告） |
| 如果 e_CDi 0.88-0.92 → MIT-like 可行，下一步接 CST/XFOIL | **未達 0.88-0.92**；upper bound 是 0.82 |
| 如果 e_CDi 仍低於 0.85 → 診斷 binder | 達成（local CL gate / target spanload / wing-area 三主因） |
| 不要把 143 W mission proxy 當 final | 達成（oracle 完全不算 mission power） |
| AVL sanity benchmark 不退化 | 達成（0.9937 / 0.8935） |

## 跑出來的工件

- `src/hpa_mdo/concept/cruise_twist_oracle.py`
- `scripts/birdman_mit_like_twist_oracle.py`
- `tests/test_concept_cruise_twist_oracle.py`（10 個 pure-function 測試）
- `output/birdman_avl_e_sanity_benchmark_post_twist_oracle/`
- `output/birdman_mit_like_twist_oracle_smoke/`（4 candidate × 30 maxfev）
- `output/birdman_mit_like_twist_oracle_validation/`（16 candidate × 30 maxfev）
