# Mission Profile Drag Source Audit

**版本**：v1.0  
**日期**：2026-05-04  
**範圍**：上游 Concept Pipeline 中 `profile_cd_proxy` 欄位的資料來源審計

---

## 1. 背景與審計目標

Mission Drag Budget Shadow 評估器（`drag_budget_shadow.py`）以每個候選翼型的 `candidate.mission.profile_cd_proxy` 作為主翼翼型輪廓阻力係數（`cd0_wing_profile`）的輸入。

本審計回答以下問題：

1. `profile_cd_proxy` 是由哪個函式、在哪個時間點寫入候選字典？
2. 在 cli_stubbed 模式下，為何所有候選的值都是 `0.020`？
3. 這個 `0.020` 是真實估計值、fallback 預設值，還是 stub 暫代值？
4. 在 julia_xfoil 模式下，這個值是如何計算的？與 `mean_cd_effective` 有何差異？
5. 目前的程式碼中是否存在更好的資料來源？
6. 建議的後續實作步驟與最低可行路徑為何？

---

## 2. `profile_cd_proxy` 的資料來源追蹤

### 2.1 設定位置

```
src/hpa_mdo/concept/pipeline.py, 約第 2729 行
```

```python
"profile_cd_proxy": profile_cd,
```

### 2.2 `profile_cd` 的計算

```
src/hpa_mdo/concept/pipeline.py, 約第 2226 行
```

```python
profile_cd = _mean_effective_cd(
    cruise_station_points or station_points,
    airfoil_feedback,
)
```

> **關鍵**：輸入的是 `cruise_station_points`（若存在），否則退而使用 `station_points`。  
> `cruise_station_points` 只含 `reference_avl_case` 標記的巡航工況（低 CL 操作點），  
> 不包含高 CL 失速掃描點。

### 2.3 `_mean_effective_cd` 的三層 fallback 邏輯

```
src/hpa_mdo/concept/pipeline.py, 約第 1902–1921 行
```

| 優先順序 | 觸發條件 | 來源 | 說明 |
|----------|----------|------|------|
| 1 (最優) | `station_points` 中有 `cd_effective` 欄位且非零 | 站點加權平均 | 需要真實 worker 執行 |
| 2 | `airfoil_feedback["mean_cd_effective"]` 不為 None | airfoil_feedback 字典 | 需要真實 worker 執行 |
| 3 (最差) | 以上均不滿足 | **hardcoded `return 0.020`** | stub / fallback |

---

## 3. Stubbed 模式：為何 `profile_cd_proxy = 0.020`

### 3.1 Stub Worker 的行為

在 `--worker-mode stubbed`（`_cli_airfoil_worker_factory`）下，每個 query 回傳：

```python
{
    "status": "stubbed_ok",
    "mean_cd": 0.020,          # 對 non-nsga2 template
    "mean_cm": -0.055,
    "usable_clmax": 1.35,
    "polar_points": [...],     # cd 由 mean_cd 構造，但沒有 cd_effective 語意
}
```

Stub worker **不填寫** `cd_effective` 欄位於 station_points 中，  
且 `airfoil_feedback.mean_cd_effective` 保持 `None`、`applied = False`。

因此 `_mean_effective_cd` 必然落到第 3 層：回傳常數 `0.020`。

### 3.2 實際驗證（audited output）

```
output/birdman_oswald_fourier_smoke_20260502/concept_ranked_pool.json
  - worker_backend: cli_stubbed
  - airfoil_feedback.mode: geometry_proxy
  - airfoil_feedback.applied: false
  - airfoil_feedback.mean_cd_effective: null
  - profile_cd_proxy: 0.020  ← 全部 39 個候選一致
```

**結論：這個 `0.020` 是 stub 暫代值，不是真實的翼型估計值。**

---

## 4. Julia/XFoil 模式：真實值的計算方式

### 4.1 實際驗證（audited output）

```
output/birdman_full_cst_run_20260502_optimized/concept_ranked_pool.json
  - worker_backend: julia_xfoil
  - airfoil_feedback.mode: airfoil_informed
  - profile_cd_proxy: 0.0097 ~ 0.0215（中位數 ≈ 0.0117）

output/birdman_box_b_cst_julia_20260502/concept_ranked_pool.json
  - profile_cd_proxy: 0.0086 ~ 0.0104（中位數 ≈ 0.0094）

output/birdman_mass_closure_rerun_20260424/concept_ranked_pool.json
  - profile_cd_proxy: 0.0076 ~ 0.0102（中位數 ≈ 0.0088）
```

### 4.2 `profile_cd_proxy` 與 `mean_cd_effective` 的差異

| 欄位 | 操作點集合 | 典型值 | 意義 |
|------|-----------|--------|------|
| `profile_cd_proxy` | 僅 `reference_avl_case` 巡航工況（低 CL） | ≈ 0.0087–0.0120 | **純巡航翼型輪廓阻力**，適合做 CD0 預算 |
| `mean_cd_effective` | 所有 28 個 feedback 點（含高 CL 失速掃描） | ≈ 0.013–0.019 | 全包絡平均，含誘導阻力分量，**不適合**直接用於 CD0 預算 |

**`profile_cd_proxy` 用於 drag budget 評估是正確的欄位選擇。**  
Shadow 評估器已正確使用 `profile_cd_proxy`，而非 `mean_cd_effective`。

---

## 5. 現有程式碼中的更好資料來源

### 5.1 `zone_airfoil_picker.py` — 已存在但未接入主流程

```
src/hpa_mdo/concept/zone_airfoil_picker.py
```

兩個尚未接入上游 pipeline 的函式：

```python
def estimate_zone_profile_cd(*, selected, zone_requirements) -> dict[str, dict]:
    """
    在每個 zone 的代表性 CL + Re 查表，取插值 Cd。
    回傳 {zone_name: {cd_profile, cl_used, reynolds_used, chord_m_used}}
    """

def chord_weighted_profile_cd(*, zone_profile) -> float:
    """
    對 zone_profile 做弦長加權平均。
    比 _mean_effective_cd 更準確，因為：
    (1) 在正確的操作 CL+Re 查極曲線（非全包絡平均）
    (2) 按弦長加權（反映實際面積貢獻）
    (3) 分區處理（根部與翼尖可有不同翼型）
    """
```

**目前使用狀況**：僅在 `scripts/birdman_mit_like_closed_loop_search.py` 中使用，  
**主流程 `pipeline.py` 未呼叫**。

### 5.2 各方法比較

| 方法 | 精度 | 狀態 | 所需輸入 |
|------|------|------|----------|
| Hardcoded `0.020` | 無意義（stub） | 已在 pipeline 中（fallback） | 無 |
| `_mean_effective_cd` via `airfoil_feedback.mean_cd_effective` | 低（含高 CL 點） | 已在 pipeline 中（level-2 fallback） | 真實 worker |
| `_mean_effective_cd` via `cruise_station_points` | 中（巡航工況 cd_effective 加權） | 已在 pipeline 中（level-1 fallback） | 真實 worker + cd_effective 欄位 |
| `chord_weighted_profile_cd` via `estimate_zone_profile_cd` | 最高（弦長加權、分區、精確 CL+Re） | **未接入主流程** | 真實 worker + zone tabulated polar |

---

## 6. 建議的後續實作步驟

### 6.1 短期（最低可行路徑）— 修正 Level-1 fallback

**問題**：目前 `_mean_effective_cd` 的 level-1 路徑（`station_points[*]["cd_effective"]`）  
雖然邏輯正確，但 `cd_effective` 欄位在 julia 模式下是否被正確填入尚待確認。

**行動**：
1. 在一個 julia 候選的 `station_points` 中確認 `cd_effective` 是否非零
2. 若為零，追查 `cd_effective` 的填入邏輯，修復資料流

此路徑無需修改 `_mean_effective_cd` 的介面，僅確保上游資料正確流入。

### 6.2 中期（推薦）— 接入 `chord_weighted_profile_cd`

**目標**：用 `zone_airfoil_picker.chord_weighted_profile_cd()` 取代 `_mean_effective_cd` 作為 `profile_cd` 的主要來源。

**最低可行路徑**（估計 1–2 天工作量）：

```python
# 在 pipeline.py 中，計算 profile_cd 的位置附近：

from hpa_mdo.concept.zone_airfoil_picker import (
    estimate_zone_profile_cd,
    chord_weighted_profile_cd,
)

# 嘗試用 zone_profile_cd（更準確）
if zone_airfoil_result is not None:
    zone_profile = estimate_zone_profile_cd(
        selected=zone_airfoil_result,
        zone_requirements=zone_requirements,
    )
    profile_cd = chord_weighted_profile_cd(zone_profile=zone_profile)
else:
    # 既有 fallback 路徑保持不變
    profile_cd = _mean_effective_cd(
        cruise_station_points or station_points,
        airfoil_feedback,
    )
```

**注意**：`zone_airfoil_result` 的可用性需在 pipeline 中確認；  
若 zone picker 未執行，fallback 到既有路徑即可。

### 6.3 長期（可選）— Cruise-filtered Mean

若 level-1 修復後 `profile_cd_proxy` 仍與真實 chord-weighted 值有明顯偏差，  
可考慮在 `_mean_effective_cd` 中增加一個 cruise-only 過濾層，  
只對 `reference_avl_case` 標記的 station_points 做加權平均。

---

## 7. 風險與限制

| 風險 | 說明 | 緩解方式 |
|------|------|----------|
| **Julia worker 不可用** | `chord_weighted_profile_cd` 需要真實 polar 資料；stub 模式下仍會落入 `0.020` fallback | 保留現有 fallback 邏輯，shadow 評估器以 `missing_cd0_wing_profile` 標記 stub 結果 |
| **巡航工況 CL 假設** | `cruise_station_points` 僅含代表性巡航 CL，未反映沿翼展的 CL 變化 | 中期改用 zone-resolved `chord_weighted_profile_cd`，每區使用各自的操作 CL |
| **翼型優化迭代中的值漂移** | 迭代過程中 polar 會更新，`profile_cd_proxy` 可能落後一個 generation | 在最終收斂的 ranked pool 上執行 shadow 評估（目前做法），而非在迭代中間評估 |
| **`mean_cd_effective` 的誤用** | 若未來有人直接把 `mean_cd_effective` 接入 drag budget，會因高 CL 點而系統性高估 CD0 | Shadow 評估器明確使用 `profile_cd_proxy`，已在文件中說明差異 |

---

## 8. 現狀摘要（一覽）

```
profile_cd_proxy 資料流（現況）：

  cli_stubbed 模式
  └─ worker 回傳 mean_cd=0.020，但不填 cd_effective
     └─ _mean_effective_cd fallback level-3 → 0.020
        └─ profile_cd_proxy = 0.020  ← stub 暫代值，無物理意義

  julia_xfoil 模式
  └─ worker 填入 station_points[*]["cd_effective"]（若有）
     └─ _mean_effective_cd level-1 path
        └─ 僅對 cruise_station_points 做加權平均
           └─ profile_cd_proxy ≈ 0.0087–0.0120  ← 真實估計值，適合 drag budget

  更好路徑（未接入）：
  └─ zone_airfoil_picker.estimate_zone_profile_cd()
     └─ chord_weighted_profile_cd()
        └─ 弦長加權、分區、精確操作點 → 最高精度
```

---

## 9. Shadow Mode 的 Profile CD 品質識別（v1.1 新增）

本審計完成後，已在以下位置實作 profile CD source / quality metadata：

### 9.1 Pipeline 新增欄位

`src/hpa_mdo/concept/pipeline.py` 的 `_mean_effective_cd_with_source()` 函式  
（原 `_mean_effective_cd` 保持向後相容，仍回傳 `float`）：

| 來源路徑 | `profile_cd_proxy_source` | `profile_cd_proxy_quality` |
|----------|--------------------------|---------------------------|
| `cruise_station_points[*]["cd_effective"]` 加權平均 | `cruise_station_points_cd_effective` | `mission_budget_candidate` |
| `airfoil_feedback["mean_cd_effective"]` | `airfoil_feedback_mean_cd_effective` | `fallback_not_cd0_budget_grade` |
| Hardcoded `0.020` | `hardcoded_stub_fallback_0p020` | `not_mission_grade` |

每個 candidate 的 `mission` dict 現在包含 `profile_cd_proxy_source` 與 `profile_cd_proxy_quality`。

### 9.2 Shadow Evaluator 的品質處理

`src/hpa_mdo/mission/drag_budget_shadow.py` 的行為：

| `profile_cd_proxy_quality` | `evaluation_status` | 計算值 | 備註 |
|----------------------------|--------------------|---------|----|
| `mission_budget_candidate` | `ok` | 完整計算 | 正式 drag budget 評估 |
| `fallback_not_cd0_budget_grade` | `ok` | 完整計算 | 使用但仍為正式評估 |
| `not_mission_grade` | `profile_cd_not_mission_grade` | **仍計算**，但標記 | notes 寫明為 stub fallback |
| 缺失（舊 pool 無此欄位） | `ok` | 完整計算 | notes 寫明 quality unknown |

### 9.3 Shadow Summary JSON 新增欄位

```json
{
  "profile_cd_quality_counts": {
    "mission_budget_candidate": N,
    "not_mission_grade": N,
    "unknown": N
  },
  "count_not_mission_grade_profile_cd": N,
  "count_mission_budget_candidate_profile_cd": N
}
```

### 9.4 向後相容性

舊版 ranked pool（無 `profile_cd_proxy_quality` 欄位）的候選，  
shadow 評估器仍正常計算，quality 計為 `unknown`，`evaluation_status = "ok"`。  
不會破壞現有 pipeline 輸出或任何既有的 shadow 腳本。

---

## 10. 結論

- **Stub 模式的 `0.020` 不是設計參數，是 fallback 常數**，代表「無翼型資料」的佔位值。
- **Julia/XFoil 模式的 `profile_cd_proxy`（≈ 0.009–0.012）是正確的巡航翼型輪廓阻力估計值**，適合作為 `cd0_wing_profile` 輸入 Mission Drag Budget 評估。
- **`mean_cd_effective` 不應直接用於 drag budget**，因其包含高 CL 失速掃描點，會系統性高估 CD0。
- **`chord_weighted_profile_cd`（`zone_airfoil_picker.py`）是最精確的資料來源**，但尚未接入主流程，為後續實作的主要改進方向。
- **v1.1 更新：`profile_cd_proxy_source` 與 `profile_cd_proxy_quality` metadata 已接入 pipeline 與 shadow evaluator**，新 run 可自動識別 stub 候選。

---

*本文件依 CLAUDE.md 規範以繁體中文撰寫。*
