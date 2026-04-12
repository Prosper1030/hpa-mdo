# Dual-Beam Decision Interface v1 Specification

更新時間：2026-04-12 CST

這份文件是 decision interface v1 的正式規格，給：

- 外部 consumer
- app / autoresearch / reporting
- `hpa-mdo` 內部維護者

## 1. 正式識別

- `schema_name = direct_dual_beam_v2m_joint_material_decision_interface`
- `schema_version = v1`

consumer 應先檢查這兩個欄位，再進一步讀 payload。

## 2. top-level schema

```json
{
  "schema_name": "direct_dual_beam_v2m_joint_material_decision_interface",
  "schema_version": "v1",
  "status": "complete",
  "decision_layer_config": {},
  "designs": []
}
```

### top-level fields

- `schema_name`
  - 固定字串
- `schema_version`
  - 目前固定為 `v1`
- `status`
  - top-level machine-readable status
- `decision_layer_config`
  - 這次 run 用到的 decision gate
- `designs`
  - 固定 3 個 design slots
  - 順序為 `primary`、`balanced`、`conservative`

## 3. top-level status enum

`status` 合法值：

- `complete`
  - 三個 slot 都是正式選中，沒有 fallback
- `complete_with_fallbacks`
  - 三個 slot 都有結果，但至少一個 slot 是 fallback 選中
- `partial`
  - 至少有一個 slot 有結果，但不是三個 slot 都有結果
- `empty`
  - 三個 slot 都沒有可用 candidate

## 4. slot schema

每個 design slot 都使用完全一致的欄位：

```json
{
  "design_class": "primary",
  "design_label": "Primary design",
  "slot_status": "selected",
  "fallback_reason_code": "none",
  "geometry_seed": "selected",
  "geometry_choice": [4, 0, 0, 2, 0],
  "material_choice": {
    "main_spar_family": "main_light_ud",
    "rear_outboard_reinforcement_pkg": "ob_none"
  },
  "mass_kg": 10.089648874728232,
  "raw_main_tip_mm": 1716.0314116847314,
  "raw_rear_tip_mm": 2439.324117400683,
  "raw_max_uz_mm": 2439.324117400683,
  "psi_u_all_mm": 2440.293712600995,
  "candidate_margin_mm": 59.70628739900485,
  "rule_trigger": "string",
  "selection_rationale": "string",
  "qualifying_candidate_count": 27
}
```

### 固定欄位定義

- `design_class`
  - `primary` / `balanced` / `conservative`
- `design_label`
  - 人類可讀 label
- `slot_status`
  - slot-level machine-readable status
- `fallback_reason_code`
  - machine-readable fallback / unavailable reason
- `geometry_seed`
  - 被選中 candidate 的 geometry seed label
  - 若無結果則為 `null`
- `geometry_choice`
  - 5 維 geometry choice indices
  - 若無結果則為 `null`
- `material_choice.main_spar_family`
  - 若無結果則為 `null`
- `material_choice.rear_outboard_reinforcement_pkg`
  - 若無結果則為 `null`
- `mass_kg`
- `raw_main_tip_mm`
- `raw_rear_tip_mm`
- `raw_max_uz_mm`
- `psi_u_all_mm`
- `candidate_margin_mm`
  - 若無結果則上述數值欄位一律為 `null`
- `rule_trigger`
  - 對應 decision rule 的固定說明
- `selection_rationale`
  - 這次 run 的具體選中原因
- `qualifying_candidate_count`
  - 該 slot 的正式 qualifying pool 大小

## 5. slot status enum

`slot_status` 合法值：

- `selected`
  - slot 依正式 rule 直接選中
- `fallback_selected`
  - slot 沒有直接命中正式 gate，改用 fallback 候選
- `unavailable`
  - slot 沒有候選可用

## 6. fallback reason enum

`fallback_reason_code` 合法值：

- `none`
- `no_pareto_candidates`
- `primary_no_non_sleeve_candidate_above_margin_floor`
- `primary_no_candidate_above_margin_floor`
- `balanced_no_candidate_meets_margin_and_mass_gate`
- `conservative_no_balanced_sleeve_candidate`

consumer 應依賴這些 enum，而不是去 parse `selection_rationale` 的自由文字。

## 7. decision layer config fields

目前 `decision_layer_config` 固定包含：

- `schema_version`
- `primary_margin_floor_mm`
- `balanced_min_margin_mm`
- `balanced_max_mass_delta_from_primary_kg`
- `conservative_mode`

這些欄位用來讓 consumer 知道這次 run 用的是哪一套 decision gate。

## 8. downstream reading rules

### 推薦讀法

1. 先檢查 `schema_name`
2. 再檢查 `schema_version`
3. 再看 top-level `status`
4. 依 `design_class` 取出 `primary / balanced / conservative`
5. 依 `slot_status` / `fallback_reason_code` 決定下游處理方式

### 不推薦做法

- 不要依賴 `designs` 陣列的自然語言內容
- 不要 parse `selection_rationale`
- 不要去讀 summary JSON 取代 decision interface JSON
- 不要直接依賴內部 script 的 stdout

## 9. v1 相容性原則

在 `schema_version = v1` 期間：

- `schema_name` 不變
- `status` enum 不變
- `slot_status` enum 不變
- `fallback_reason_code` enum 不變
- 三個 slot 的固定欄位集合不變

若未來要破壞這些約定，應升版 `schema_version`。
