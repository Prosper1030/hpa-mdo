# Profile Drag Estimator Integration Plan

**版本**：v1.0
**日期**：2026-05-05
**作者**：AI Tech Lead（Claude）
**狀態**：整合計畫草案，待 Codex 實作

---

## 1. 現況

### 1.1 背景

Mission Drag Budget Shadow 評估器（`drag_budget_shadow.py`）以
`candidate.mission.profile_cd_proxy` 作為主翼翼型輪廓阻力（CD0\_wing\_profile）的輸入。
目前有兩種運行情況：

| 執行模式 | `profile_cd_proxy` 典型值 | 品質 |
|---------|--------------------------|------|
| `cli_stubbed` | `0.020`（固定常數） | 無物理意義，Stub 暫代 |
| `julia_xfoil` | `0.0087–0.0120`（中位 ≈ 0.0094） | 真實巡航翼型輪廓阻力估計，可用於 drag budget |

v1.1 已新增 `profile_cd_proxy_source` / `profile_cd_proxy_quality` metadata，
Shadow 評估器已可辨別哪些候選的 profile CD 有實際意義。

### 1.2 尚未完成的事

目前 `julia_xfoil` 模式下的 `profile_cd_proxy` 來自
`_mean_effective_cd_with_source()`，使用巡航工況站點的
`cd_effective` 做加權平均（**level-1 路徑**）。

更精確的方法已存在於 `zone_airfoil_picker.py`：

- `estimate_zone_profile_cd(selected, zone_requirements)` — 在正確的 CL＋Re 查詢各 zone 的極曲線
- `chord_weighted_profile_cd(zone_profile)` — 弦長加權合成全翼 profile CD

這兩個函式已在 `scripts/birdman_mit_like_closed_loop_search.py` 中使用，
但主流程 `pipeline.py` 的 `_build_concept_mission_summary()` 尚未接入。

---

## 2. 現有 profile\_cd\_proxy 資料流

### 2.1 設定位置

```
src/hpa_mdo/concept/pipeline.py，約 L2748
```

```python
"profile_cd_proxy": profile_cd,
"profile_cd_proxy_source": profile_cd_source,
"profile_cd_proxy_quality": profile_cd_quality,
```

### 2.2 計算位置

```
src/hpa_mdo/concept/pipeline.py，約 L2245
```

```python
profile_cd, profile_cd_source, profile_cd_quality = _mean_effective_cd_with_source(
    cruise_station_points or station_points,
    airfoil_feedback,
)
```

呼叫者：`_build_concept_mission_summary()`（L2231）。
此函式目前**不接受** `zone_requirements` 或 `selected_by_zone` 參數。

### 2.3 `_mean_effective_cd_with_source()` 的三層 fallback（L1910–L1931）

| 優先順序 | 觸發條件 | `profile_cd_proxy_source` | `profile_cd_proxy_quality` |
|---------|---------|--------------------------|---------------------------|
| 1（最優） | `cruise_station_points[*]["cd_effective"]` 有非零值 | `cruise_station_points_cd_effective` | `mission_budget_candidate` |
| 2 | `airfoil_feedback["mean_cd_effective"]` 不為 None | `airfoil_feedback_mean_cd_effective` | `fallback_not_cd0_budget_grade` |
| 3（最差） | 以上均不滿足 | `hardcoded_stub_fallback_0p020` | `not_mission_grade` |

### 2.4 Stub 模式的 fallback 原因

在 `cli_stubbed` 模式下，Stub worker 不填入 `cd_effective` 欄位，
`airfoil_feedback.mean_cd_effective` 也保持 `None`。
因此 `_mean_effective_cd_with_source()` 必然落到第 3 層，回傳常數 `0.020`。

### 2.5 julia\_xfoil 模式下的 profile\_cd\_proxy 來源

Julia worker 填入 `station_points[*]["cd_effective"]`，
`_mean_effective_cd_with_source()` 取 `cruise_station_points`（僅
`reference_avl_case` 標記的巡航工況）做加權平均，得到 ≈ 0.0087–0.0120 的真實估計值。

---

## 3. zone\_airfoil\_picker 可接入性分析

### 3.1 `estimate_zone_profile_cd()` 需要的輸入

```
src/hpa_mdo/concept/zone_airfoil_picker.py，L254–L277
```

| 參數 | 型別 | 說明 |
|------|------|------|
| `selected` | `Mapping[str, ZoneAirfoilSpec]` | 各 zone 已選的翼型規格 |
| `zone_requirements` | `Mapping[str, dict[str, Any]]` | 各 zone 的 AVL 輸出（含 `points`：cl\_target、reynolds、chord\_m） |

**回傳**：`dict[str, dict[str, float]]`，每 zone 包含 `cd_profile`、`cl_used`、`reynolds_used`、`chord_m_used`。

### 3.2 `chord_weighted_profile_cd()` 需要的輸入

```
src/hpa_mdo/concept/zone_airfoil_picker.py，L280–L302
```

| 參數 | 型別 | 說明 |
|------|------|------|
| `zone_profile` | `Mapping[str, Mapping[str, float]]` | `estimate_zone_profile_cd()` 的回傳值 |

**回傳**：`float`，弦長加權的全翼 profile CD。

### 3.3 zone\_requirements 在主 pipeline 中的可用性

`zone_requirements` 是 `_evaluate_selected_airfoils_for_concept()`（L3147）的輸入參數，
在整個函式內部**全程可用**。然而：

- `_build_concept_mission_summary()`（L2231）目前**不接受** `zone_requirements`
- `_build_concept_mission_summary()` 在 L3234 被呼叫，此時 `zone_requirements` 在範圍內但未傳入
- **結論**：`zone_requirements` 資料在正確位置存在，只是尚未穿線傳入

### 3.4 selected（ZoneAirfoilSpec）與 selected\_by\_zone（SelectedZoneCandidate）的差異

這是接入的核心技術障礙：

| 物件 | 所在模組 | 包含資料 | 能否用於 `estimate_zone_profile_cd()` |
|------|---------|---------|--------------------------------------|
| `ZoneAirfoilSpec` | `zone_airfoil_picker.py` | 種子庫翼型 + 二次多項式 polar + `cd_at(cl, re)` 方法 | **可以**（直接 API） |
| `SelectedZoneCandidate` | `airfoil_selection.py` | CST 翼型 + `mean_cd` + `mean_cm` + `usable_clmax` | **不行**（無 `cd_at()` 方法，也不是 ZoneAirfoilSpec） |

主 pipeline 使用 `SelectedZoneCandidate`（CST 搜尋結果）；
`estimate_zone_profile_cd()` 期望 `ZoneAirfoilSpec`（種子庫 picker 結果）。

### 3.5 birdman\_mit\_like\_closed\_loop\_search.py 的呼叫模式

```
scripts/birdman_mit_like_closed_loop_search.py，L311–L355
```

```python
selected_specs = select_zone_airfoils_from_library(zone_requirements=no_airfoil_zone)
# ...
profile_per_zone = estimate_zone_profile_cd(
    selected=selected_specs,           # ZoneAirfoilSpec 物件
    zone_requirements=with_airfoil_zone,  # 含翼型的 AVL 輸出
)
cd_profile_total = chord_weighted_profile_cd(zone_profile=profile_per_zone)
```

該腳本先呼叫 `select_zone_airfoils_from_library()` 取得 `ZoneAirfoilSpec`，
再傳入 `estimate_zone_profile_cd()`。主 pipeline 沒有這個中間步驟。

### 3.6 接入條件總結

| 條件 | 現況 | 缺什麼 |
|------|------|--------|
| `zone_requirements` 資料存在 | 存在於 `_evaluate_selected_airfoils_for_concept()` 範圍內 | 需傳入 `_build_concept_mission_summary()` |
| `ZoneAirfoilSpec` 物件存在 | **不存在**；主 pipeline 只有 `SelectedZoneCandidate` | 需額外呼叫 `select_zone_airfoils_from_library()` 或設計 adapter |
| `estimate_zone_profile_cd()` API 穩定 | 已可用 | 無 |
| `chord_weighted_profile_cd()` API 穩定 | 已可用 | 無 |
| 不影響 ranking / objective | 需要確保 | 整合點只在 `_build_concept_mission_summary()` 的 metadata 段 |

---

## 4. 建議的 profile drag source 優先順序

整合後的優先順序設計（新增 level-0）：

```
Level-0（最優）：zone_chord_weighted_profile_cd
  條件：zone_requirements 有帶 points 的 zone，且可從種子庫選出 ZoneAirfoilSpec
  實作：select_zone_airfoils_from_library(zone_requirements)
        → estimate_zone_profile_cd(selected, zone_requirements)
        → chord_weighted_profile_cd(zone_profile)

Level-1：cruise_station_points_cd_effective
  條件：julia 模式，cruise_station_points 有 cd_effective 欄位
  實作：現有 _mean_effective_cd_with_source() level-1 路徑（保持不變）

Level-2：airfoil_feedback_mean_cd_effective
  條件：julia 模式，airfoil_feedback["mean_cd_effective"] 不為 None
  實作：現有 _mean_effective_cd_with_source() level-2 路徑（保持不變）
  注意：此路徑包含高 CL 點，不適合直接用於 CD0 budget

Level-3（最差）：hardcoded_stub_fallback_0p020
  條件：以上均不滿足（Stub 模式）
  實作：現有 _mean_effective_cd_with_source() level-3 路徑（保持不變）
```

---

## 5. source / quality metadata 設計

### 5.1 source tag 命名（profile\_cd\_proxy\_source）

| source tag | 對應路徑 | 說明 |
|-----------|---------|------|
| `zone_chord_weighted_profile_cd` | Level-0（新增） | 弦長加權、分 zone、種子庫 polar，最準確 |
| `cruise_station_points_cd_effective` | Level-1（現有） | 巡航站點 cd\_effective 加權平均 |
| `airfoil_feedback_mean_cd_effective` | Level-2（現有） | 全包絡平均，含高 CL 點 |
| `hardcoded_stub_fallback_0p020` | Level-3（現有） | 常數 fallback，無物理意義 |

### 5.2 quality tag 命名（profile\_cd\_proxy\_quality）

| quality tag | 適用條件 | 是否可用於 mission-grade drag budget |
|------------|---------|--------------------------------------|
| `mission_budget_candidate` | Level-0 或 Level-1 | **是** |
| `fallback_not_cd0_budget_grade` | Level-2 | 可使用，但需注意高 CL 點偏差 |
| `not_mission_grade` | Level-3 | **否**，為 Stub 暫代值 |
| `unknown` | 舊版 pool 無此欄位 | 未知，保守對待 |

**設計原則**：Level-0 使用種子庫 polar 查詢（非 CST 全域搜尋），
仍屬於工程估計，品質標為 `mission_budget_candidate`，
因為它在正確的巡航 CL+Re 點查詢，且按弦長加權，物理意義明確。

---

## 6. 分階段實作計畫

### Phase 1：Adapter 層 + 函式介面擴充（不影響 ranking）

**目標**：讓 `_build_concept_mission_summary()` 能接收 `zone_requirements`，
並嘗試呼叫 `select_zone_airfoils_from_library()` + `estimate_zone_profile_cd()`。

**要改的檔案**：

| 檔案 | 修改內容 |
|------|---------|
| `src/hpa_mdo/concept/pipeline.py` | 擴充 `_build_concept_mission_summary()` signature，加入 `zone_requirements: dict[str, dict] \| None = None` 參數 |
| `src/hpa_mdo/concept/pipeline.py` | 在 L3234 的呼叫點，將 `zone_requirements` 傳入 |
| `src/hpa_mdo/concept/pipeline.py` | 新增 `_zone_chord_weighted_profile_cd()` helper 函式（封裝 picker 呼叫） |

**新函式概念**（僅示意，不是要求照抄）：

```python
def _zone_chord_weighted_profile_cd(
    zone_requirements: dict[str, dict[str, Any]],
) -> float | None:
    """Attempt zone-based profile CD from seed library polar.
    Returns None if zone_requirements is empty or has no points.
    """
    from hpa_mdo.concept.zone_airfoil_picker import (
        select_zone_airfoils_from_library,
        estimate_zone_profile_cd,
        chord_weighted_profile_cd,
    )
    zones_with_points = {
        k: v for k, v in zone_requirements.items()
        if v.get("points")
    }
    if not zones_with_points:
        return None
    try:
        selected = select_zone_airfoils_from_library(zone_requirements=zones_with_points)
        zone_profile = estimate_zone_profile_cd(
            selected=selected,
            zone_requirements=zones_with_points,
        )
        cd = chord_weighted_profile_cd(zone_profile=zone_profile)
        return cd if cd > 0.0 else None
    except Exception:
        return None
```

**要新增的測試**：

```
tests/concept/test_pipeline_profile_cd_zone.py
```

- `zone_requirements` 含有效 points 時，helper 回傳含正值 CD 的 diagnostic dict
- `zone_requirements` 為空或無 points 時，helper 回傳 unavailable diagnostic dict
- helper 內部發生例外時，回傳 unavailable diagnostic dict（不 raise）
- `_build_concept_mission_summary()` 加入 `zone_requirements` 後，仍與舊版呼叫相容（`zone_requirements=None`）

**驗收條件**：

- `profile_cd_proxy_source` / `profile_cd_proxy_quality` 欄位繼續正確輸出
- 舊版呼叫（不傳 `zone_requirements`）行為不變
- 所有現有測試通過

**失敗時 fallback**：`zone_requirements=None` 或 zone estimator 失敗時，
primary `profile_cd_proxy` 仍直接走現有 `_mean_effective_cd_with_source()` 路徑，
zone 欄位只記錄 unavailable diagnostic。

---

### Phase 1 實作結果 / diagnostic integration（2026-05-05）

本次實作採用 **diagnostic integration**，不是 Phase 2 的 primary-source
切換。因此目前主流程同時計算：

- 既有 `profile_cd_proxy`
- `profile_cd_proxy_source`
- `profile_cd_proxy_quality`
- 新增的 `profile_cd_zone_chord_weighted`
- 新增的 `profile_cd_zone_source`
- 新增的 `profile_cd_zone_quality`
- 新增的 `profile_cd_zone_vs_proxy_delta`
- 新增的 `profile_cd_zone_vs_proxy_ratio`

實作重點：

1. `profile_cd_proxy` 仍完全由 `_mean_effective_cd_with_source()` 產生。
2. `cruise_station_points_cd_effective` 仍標為 `mission_budget_candidate`。
3. `airfoil_feedback_mean_cd_effective` 仍標為 `fallback_not_cd0_budget_grade`。
4. `hardcoded_stub_fallback_0p020` 仍標為 `not_mission_grade`。
5. zone-based estimator 只寫入 diagnostic 欄位，不修改 `misc_cd_proxy`、
   `total_cd`、`mission_feasible`、`mission_score`、objective、ranking 或 gate。

新增 helper：

```python
_try_zone_chord_weighted_profile_cd(zone_requirements)
```

成功時回傳：

```json
{
  "profile_cd_zone_chord_weighted": 0.011,
  "profile_cd_zone_source": "zone_chord_weighted_seed_library",
  "profile_cd_zone_quality": "diagnostic_seed_library_estimate",
  "profile_cd_zone_error": null
}
```

失敗或資料不足時回傳：

```json
{
  "profile_cd_zone_chord_weighted": null,
  "profile_cd_zone_source": "zone_chord_weighted_unavailable",
  "profile_cd_zone_quality": "unavailable"
}
```

Shadow mode 也已擴充為 diagnostic 報告用途：

- CSV 新增 zone diagnostic 欄位。
- Summary JSON 新增 `profile_cd_source_counts`、`profile_cd_quality_counts`、
  `profile_cd_zone_source_counts`、`profile_cd_zone_quality_counts`、
  `count_zone_profile_available`、`count_zone_profile_unavailable`、
  `profile_cd_zone_vs_proxy_ratio_min/median/max`。
- run output 會新增 `mission_profile_cd_comparison.md`，列出 source/quality
  counts、proxy/zone CD 分布、zone/proxy ratio，以及 delta 最大的前 10 個候選。

下一步若要把 zone source 升級成 primary，必須另開任務：

- 先用 julia/XFOIL ranked pool 對比 `profile_cd_proxy` vs
  `profile_cd_zone_chord_weighted`。
- 確認 zone seed-library polar 與 CST/XFOIL worker 的物理差距。
- 明確評估 `misc_cd_proxy`、`total_cd`、mission feasibility、objective 和 ranking
  的變動幅度。
- 決定是否需要 opt-in flag（例如 `profile-cd-source-policy`），且預設仍應維持
  existing 行為直到通過數值審核。

---

### Phase 2：Level-0 正式接入主 pipeline

**目標**：在 `zone_requirements` 有有效 points 時，`profile_cd_proxy` 使用
`zone_chord_weighted_profile_cd` 作為 primary source，取代 Level-1。

**要改的檔案**：

| 檔案 | 修改內容 |
|------|---------|
| `src/hpa_mdo/concept/pipeline.py` | 在 `_build_concept_mission_summary()` 中，優先嘗試 Level-0；成功時設定對應 source/quality tag |
| `src/hpa_mdo/concept/pipeline.py` | 加入 `_PROFILE_CD_SOURCE_ZONE = "zone_chord_weighted_profile_cd"` 常數 |

**修改邏輯概念**（在 `_build_concept_mission_summary()` 中）：

```python
# 嘗試 Level-0（zone-based）
profile_cd = None
if zone_requirements:
    profile_cd = _zone_chord_weighted_profile_cd(zone_requirements)

if profile_cd is not None:
    profile_cd_source = _PROFILE_CD_SOURCE_ZONE
    profile_cd_quality = _PROFILE_CD_QUALITY_MISSION
else:
    # 既有 Level-1/2/3 fallback
    profile_cd, profile_cd_source, profile_cd_quality = _mean_effective_cd_with_source(
        cruise_station_points or station_points,
        airfoil_feedback,
    )
```

**要新增的測試**：

```
tests/concept/test_pipeline_profile_cd_zone.py
```

- zone 資料完整時，`profile_cd_proxy_source == "zone_chord_weighted_profile_cd"`
- zone 資料完整時，`profile_cd_proxy_quality == "mission_budget_candidate"`
- zone 資料缺失時，fallback 到 `cruise_station_points_cd_effective`（level-1）
- zone 估算值在物理合理範圍（0.007–0.015）
- zone 估算不改變任何 ranking / objective 輸出

**驗收條件**：

- julia 模式 run：`profile_cd_proxy_source == "zone_chord_weighted_profile_cd"` 出現於大多數候選
- stubbed 模式 run：所有候選仍為 `hardcoded_stub_fallback_0p020`（因為 zone points 通常需要 AVL 輸出）
- `python examples/blackcat_004_optimize.py` 正常完成，結果在驗收範圍內
- Shadow CSV 的 `cd0_wing_profile` 欄位有顯著比例標為 `zone_chord_weighted_profile_cd`

**失敗時 fallback**：任何例外 → Level-1/2/3 路徑，行為完全不變。

---

### Phase 3：Shadow Summary 品質統計改善

**目標**：在 Shadow Summary JSON 中顯示 profile CD source 分布，
讓工程師能快速確認 mission-grade profile CD 覆蓋率。

**要改的檔案**：

| 檔案 | 修改內容 |
|------|---------|
| `src/hpa_mdo/mission/drag_budget_shadow.py` | `_build_shadow_summary()` 中新增 per-source 統計欄位 |

**新增欄位概念**（在 summary JSON 中）：

```json
{
  "profile_cd_source_counts": {
    "zone_chord_weighted_profile_cd": 35,
    "cruise_station_points_cd_effective": 2,
    "airfoil_feedback_mean_cd_effective": 0,
    "hardcoded_stub_fallback_0p020": 2,
    "unknown": 0
  },
  "profile_cd_quality_counts": {
    "mission_budget_candidate": 37,
    "fallback_not_cd0_budget_grade": 0,
    "not_mission_grade": 2,
    "unknown": 0
  },
  "count_zone_cd_source_candidates": 35
}
```

**要新增的測試**：

- `_build_shadow_summary()` 在 zone source 候選出現時，
  正確計算 `profile_cd_source_counts["zone_chord_weighted_profile_cd"]`
- 舊版 pool（無 source 欄位）仍正常計算，`unknown` count 正確

**驗收條件**：

- Shadow summary JSON 包含 `profile_cd_source_counts` 欄位
- 舊版 pool JSON 不會出錯（向後相容）

**失敗時 fallback**：此 Phase 為純加法（只新增統計欄位），無 fallback 問題。

---

## 7. 測試計畫

以下測試清單供實作時參考，**目前尚未實作**。

### 7.1 Unit Tests（`tests/concept/test_pipeline_profile_cd_zone.py`）

| 測試名稱 | 測試目標 |
|---------|---------|
| `test_zone_cd_helper_with_valid_zones` | zone 資料完整時，helper 回傳 0.007–0.015 的 float |
| `test_zone_cd_helper_with_empty_zones` | zone 空時，helper 回傳 None |
| `test_zone_cd_helper_with_no_points` | zone 有鍵但無 points 時，helper 回傳 None |
| `test_zone_cd_helper_exception_safety` | 內部發生例外時，helper 回傳 None，不 raise |
| `test_build_mission_summary_zone_source` | zone 資料完整時，`profile_cd_proxy_source == "zone_chord_weighted_profile_cd"` |
| `test_build_mission_summary_zone_quality` | zone 資料完整時，`profile_cd_proxy_quality == "mission_budget_candidate"` |
| `test_build_mission_summary_fallback_to_level1` | zone 缺失時，fallback 到 `cruise_station_points_cd_effective` |
| `test_build_mission_summary_no_zone_arg` | `zone_requirements=None` 時，行為與舊版完全一致 |

### 7.2 Quality Guard Tests

| 測試名稱 | 測試目標 |
|---------|---------|
| `test_mean_cd_effective_not_mission_grade_on_stub` | stubbed 模式下 `profile_cd_proxy_quality == "not_mission_grade"` |
| `test_mean_cd_effective_fallback_not_cd0_budget` | `mean_cd_effective` fallback 標為 `fallback_not_cd0_budget_grade` |
| `test_ranked_pool_contains_source_and_quality` | ranked_pool JSON 每個候選都有 `profile_cd_proxy_source` 和 `profile_cd_proxy_quality` |

### 7.3 Shadow Integration Tests

| 測試名稱 | 測試目標 |
|---------|---------|
| `test_shadow_source_counts_in_summary` | Summary JSON 包含 `profile_cd_source_counts` |
| `test_shadow_not_mission_grade_still_evaluated` | `not_mission_grade` 候選仍計算，但 status 為 `profile_cd_not_mission_grade` |
| `test_shadow_no_change_to_ranking` | Shadow 評估不改變候選的 ranking 分數或 gate 結果 |

### 7.4 Integration Smoke Test

執行 `python examples/blackcat_004_optimize.py` 後，確認：

- `failure_index <= 0`
- `twist_max_deg <= 2.0`
- `total_mass_full_kg` 在 15–50 kg
- `val_weight` 輸出正常

---

## 8. 風險與注意事項

### 8.1 不能把 `mean_cd_effective` 當 CD0\_wing\_profile 的原因

`airfoil_feedback["mean_cd_effective"]` 是對**所有 28 個 feedback 點**的平均，
包含高 CL 失速掃描點（CL ≈ 1.4–1.8）。這些點的 cd 包含：

1. 黏性 profile drag（隨 CL 增加，攻角大，摩擦阻力增加）
2. 壓差阻力分量（靠近失速，分離阻力顯著）
3. 誘導阻力分量（若 cd\_effective 定義含 CDi）

巡航 CD0 預算只應包含**低攻角巡航工況下的翼型 profile drag**（純摩擦＋壓差，不含誘導）。
若用 `mean_cd_effective`，會系統性高估 CD0\_wing\_profile ≈ 40–100%。

### 8.2 不能把高 CL / stall sweep 點混進巡航 CD0 budget 的原因

HPA 的設計飛行條件是低速巡航（CL ≈ 0.8–1.2）。Drag budget 的邊界值是
針對此操作點校準的（例如 `cd0_wing_profile_target ≈ 0.009–0.012`）。

若混入 CL ≈ 1.6 的 stall sweep 點，估算的 profile CD 可能高達 0.015–0.020，
會讓本來通過 drag budget 的候選被錯誤分類為 `over_budget`，
破壞 drag budget 作為 concept selector 的判別力。

### 8.3 chord-weighted profile CD 與 area-weighted / station mean 的差異

| 方法 | 加權依據 | 差異 |
|------|---------|------|
| Station mean（`_mean_effective_cd` level-1） | 各站點 weight 欄位（非嚴格面積） | 所有站點等重，翼尖佔比可能過高 |
| Area-weighted（理論） | 面積微元 c(y)·dy | 最物理準確，但需積分 |
| Chord-weighted（`chord_weighted_profile_cd`） | chord\_m\_used（代表弦長） | 近似面積加權；弦大的區（翼根）佔比正確 |

弦長加權是面積加權的合理近似（面積 ≈ chord × span fraction，
若 zone span fraction 均等，則 chord 加權 ≈ 面積加權）。

### 8.4 zone-based estimate 可能缺失的資料

| 缺失情況 | 影響 | 處理方式 |
|---------|------|---------|
| `zone_requirements` 無 AVL points | 無法取得 CL+Re 資訊 | 回傳 None，fallback 到 Level-1 |
| zone 名稱不在 `_SEED_LIBRARY` 中 | `_pick_seed_for_zone()` 選不到 | 現有邏輯預設 fallback 到 Clark-Y |
| `chord_m_used` 為零 | `chord_weighted_profile_cd()` 跳過該 zone | 已有防護（L291） |

### 8.5 zone polar 是 sparse / failed XFOIL 的處理

`zone_airfoil_picker.py` 目前使用的是**種子庫的解析 polar 公式**
（`cd = polar_cd0 * Re_correction + polar_k * (cl - cl_ref)²`），
不是 XFOIL 實際跑出的極曲線。因此：

- 不會有 XFOIL 失敗問題（這是離線擬合的多項式，永遠有值）
- 但也表示 Level-0 的精度取決於種子庫 polar 的擬合品質
- 若 julia_xfoil 的 `cd_effective` 資料存在（Level-1），Level-1 資料更接近真實翼型的 XFOIL polar
- **因此**：若 Level-1 資料存在，Level-0（種子庫 polar）的優先順序可以再討論

> **設計決策待確認**：Level-0（種子庫 polar + zone-resolved）與 Level-1
> （julia XFOIL cd\_effective + cruise 過濾）何者優先？
> 目前建議 Level-0 優先，原因是 Level-0 在**正確的操作 CL+Re** 查詢，
> 不受高 CL 點污染；但 Level-1 使用的是真實翼型極曲線（而非種子庫近似）。
> 此取捨需要工程師確認後再定案。

### 8.6 這個修改不應影響 ranking / objective / hard gate

保證方法：

1. `_zone_chord_weighted_profile_cd()` 只出現在 `_build_concept_mission_summary()` 中的 metadata 段
2. `profile_cd_proxy` 本身已被用於 objective 公式（`_build_concept_mission_summary()`
   中的 `misc_cd` 計算依賴 `profile_cd`），因此修改值會影響 `misc_cd`

> **重要警告**：`profile_cd` 被用於 `misc_cd_proxy()` 計算（L2280–L2283）：
> ```python
> misc_cd = misc_cd_proxy(
>     profile_cd=profile_cd,
>     tail_area_ratio=tail_area_ratio,
>     proxy_cfg=cfg.aero_proxies.parasite_drag,
> )
> ```
> 改變 `profile_cd` 的值，會影響 `misc_cd`，進而影響 `total_cd`，
> **可能影響 mission feasibility 評估結果**。
>
> Phase 2 實作時**必須確認**：
> - 若 Level-0 給出的 CD 比 Level-1 低，可能讓更多候選通過 mission feasibility
> - 若 Level-0 給出的 CD 比 Level-1 高（種子庫翼型較差），可能讓某些候選失敗
> - 在測試中對比 Level-0 前後的 mission_feasible 分布，確認影響幅度

---

## 9. 結論

### 9.1 任務範圍確認

本文件為純計畫文件，**未修改任何 production code**。
所有分析基於以下六個檔案的原始碼閱讀：

- `docs/mission_profile_drag_source_audit.md`（既有審計基礎）
- `src/hpa_mdo/concept/pipeline.py`（主資料流）
- `src/hpa_mdo/concept/zone_airfoil_picker.py`（目標函式）
- `scripts/birdman_mit_like_closed_loop_search.py`（使用範例）
- `src/hpa_mdo/mission/drag_budget_shadow.py`（下游消費者）
- `src/hpa_mdo/mission/drag_budget.py`（drag budget 合約）

### 9.2 現有接點摘要

| 接點 | 位置 | 現況 |
|------|------|------|
| `profile_cd` 寫入 | `pipeline.py` L2748 | 正常，已有 source/quality metadata |
| `_mean_effective_cd_with_source()` | `pipeline.py` L1910 | 正常，三層 fallback 完整 |
| `_build_concept_mission_summary()` | `pipeline.py` L2231 | 未接 zone 資料 |
| `zone_requirements` 的存在位置 | `pipeline.py` L3234 呼叫點外部 | 資料存在，但未傳入 |
| `select_zone_airfoils_from_library()` | `zone_airfoil_picker.py` | 可直接呼叫，不需 worker |
| `estimate_zone_profile_cd()` | `zone_airfoil_picker.py` | 可直接呼叫，僅需種子庫 |

### 9.3 zone\_airfoil\_picker 接入條件

**可以接入**，但需解決型別不匹配問題：
主 pipeline 的 `SelectedZoneCandidate` 不能直接用於 `estimate_zone_profile_cd()`，
必須**另外呼叫** `select_zone_airfoils_from_library()` 取得 `ZoneAirfoilSpec`。

這意味著 Level-0 使用的是**種子庫 polar（非 CST 搜尋 polar）**，
是一個獨立的估計路徑，不是對 CST 結果的直接讀取。

### 9.4 最小實作方案

```
Phase 1（最小可行）：
  1. 修改 _build_concept_mission_summary() 接受 zone_requirements 參數
  2. 在呼叫點傳入 zone_requirements
  3. 新增 _zone_chord_weighted_profile_cd() helper
  4. 新增對應 unit tests
  工作量估計：0.5 天
  風險：低（只改 signature，加 try/except，無行為改變）

Phase 2：
  1. 在 _build_concept_mission_summary() 中，Level-0 作為優先來源
  2. 更新 source/quality constants
  3. 整合測試 + 手動確認對 misc_cd / mission_feasible 的影響幅度
  工作量估計：0.5 天
  風險：中（misc_cd 依賴 profile_cd，需要確認數值影響範圍）

Phase 3：
  1. Shadow summary 新增 profile_cd_source_counts
  2. 新增統計欄位的單元測試
  工作量估計：0.25 天
  風險：極低（純加法）
```

### 9.5 最大風險

**風險 1（優先確認）**：Level-0（種子庫 polar）給出的 CD 值，
可能與 Level-1（julia XFOIL cd\_effective）有顯著偏差（±20–40%），
因為種子庫只有兩個翼型（FX 76-MP-140 / Clark-Y）且 polar 為二次擬合。
需要在一個 julia run 上對比 Level-0 vs Level-1 的值，確認偏差範圍再決定是否升為 primary。

**風險 2**：`profile_cd` 改變影響 `misc_cd`，進而影響 mission_feasible 評估。
Phase 2 實作時需要對比前後的 mission_feasible 通過率，確認影響在可接受範圍內。

### 9.6 建議

**建議在 Codex 實作前完成以下確認**：

1. 在一個現有 julia run 的 ranked pool 上，手動計算 Level-0 值，
   與 Level-1 值對比，確認偏差 < 20%
2. 確認工程師對 Level-0 / Level-1 優先順序的取捨決策（見 §8.5）
3. Phase 1 可以先進行（只加 signature，無行為改變），Phase 2 等確認後再實作

Phase 1 可以交由 Codex 實作；Phase 2 實作前需要工程師確認 §8.5 的設計決策。

---

*本文件依 CLAUDE.md 規範以繁體中文撰寫。終端機 Log、程式碼片段與 JSON key 保持英文。*
