# Dual-Beam Joint Geometry + Material Decision Interface Hardening

產出時間：2026-04-12 CST

## 目的

這一輪不是再定義規則，而是把已經定好的 decision layer 正式固化成 workflow 的穩定輸出。

維持不變：

- 不重建主線
- 不再擴 search
- 不加新材料軸
- 不碰 `rear_spar_family`
- 不碰 rib/link
- 不碰 derivatives
- 不改 STEP export

主程式：
[scripts/direct_dual_beam_v2m_joint_material.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_joint_material.py)

## 這次固化的內容

### 1. decision layer 正式成為 workflow 輸出的一部分

workflow 現在除了原本的：

- report
- summary JSON

之外，會固定再輸出：

- [decision interface json](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow_interface/direct_dual_beam_v2m_joint_material_decision_interface.json)
- [decision interface text](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow_interface/direct_dual_beam_v2m_joint_material_decision_interface.txt)

### 2. 固定 decision interface schema

每個 design class 都會穩定輸出：

- `design_class`
- `design_label`
- `geometry_seed`
- `geometry_choice`
- `material_choice.main_spar_family`
- `material_choice.rear_outboard_reinforcement_pkg`
- `mass_kg`
- `raw_main_tip_mm`
- `raw_rear_tip_mm`
- `raw_max_uz_mm`
- `psi_u_all_mm`
- `candidate_margin_mm`
- `rule_trigger`
- `selection_rationale`
- `qualifying_candidate_count`

### 3. decision layer 參數可配置

目前開放成簡單參數：

- `--primary-margin-floor-mm`
- `--balanced-min-margin-mm`
- `--balanced-max-mass-delta-kg`
- `--conservative-mode`

其中 `conservative-mode` 目前固定支援：

- `max_margin`

這些參數也會一起寫進 decision interface，避免日後不知道當時是用哪一套門檻選出的。

## 目前 workflow 的穩定輸出

### Primary design

- geometry choice = `(4, 0, 0, 2, 0)`
- material choice = `main_light_ud / ob_none`
- mass = `10.089649 kg`
- raw main tip = `1716.031 mm`
- raw rear tip = `2439.324 mm`
- raw max `|UZ|` = `2439.324 mm`
- `psi_u_all = 2440.294 mm`
- candidate margin = `59.706 mm`
- rule trigger = primary release candidate with reserve floor and no-sleeve preference

### Balanced design

- geometry choice = `(4, 0, 2, 4, 0)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.302837 kg`
- raw main tip = `1692.112 mm`
- raw rear tip = `2313.829 mm`
- raw max `|UZ|` = `2313.829 mm`
- `psi_u_all = 2315.227 mm`
- candidate margin = `184.773 mm`
- rule trigger = sleeve-on balanced band with minimum margin and bounded mass premium

### Conservative design

- geometry choice = `(4, 0, 2, 4, 1)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.925947 kg`
- raw main tip = `1577.185 mm`
- raw rear tip = `2166.437 mm`
- raw max `|UZ|` = `2166.437 mm`
- `psi_u_all = 2168.143 mm`
- candidate margin = `331.857 mm`
- rule trigger = highest-margin sleeve-on Pareto candidate

## 工程判斷

### 這套 decision layer 是否已經正式固化成 workflow 的一部分

是。

它現在不是只存在於一次性的 phase note，也不是只埋在大型 summary 裡；
而是 workflow 每次執行都會穩定輸出 dedicated decision interface。

### 是否已經夠當第一版自動化 / autoresearch / app 的 decision layer

是，已經夠當第一版。

理由：

- schema 固定
- 三類設計槽位固定
- 規則門檻可配置
- 輸出欄位完整
- 文字版與 JSON 版都可直接消費

### 還缺什麼才更像產品級輸出

還差的比較像產品化配套，而不是工程邏輯本身：

- schema versioning 更正式
- 往後相容欄位約定
- 更明確的 machine-readable status / error handling
- 若無 qualifying candidate 時的 fallback code / reason enum

### 下一步最值得做什麼

下一步最值得做的是：

1. 固化更多 reporting / interface
2. 把這套 decision interface 和 app / autoresearch 的消費端對齊
3. 之後才考慮更後面的研究議題

現在還不需要拉 `rear_spar_family`。
rib/link 更後面。
