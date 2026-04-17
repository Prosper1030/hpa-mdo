# Dual-Beam Workflow Architecture Overview

更新時間：2026-04-12 CST

如果你是第一次進 repo，請先看 [README.md](../README.md)；想找文件入口與近期路線，請看 [docs/README.md](README.md) 與 [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md)。這份文件只負責說明目前 dual-beam 正式 workflow 與 producer / consumer 邊界。

這份文件是給兩種人看的：

- `hpa-mdo` 內部維護者：確認目前 dual-beam 線有哪些層、哪些屬於研究內部
- 外部 consumer：確認哪些輸出可以當成穩定 producer contract

## 1. 目前 dual-beam workflow 的層次

目前 `hpa-mdo` 這條 dual-beam 線可以分成下面幾層：

1. **Production structural mainline**
   - 位置：
     - [src/hpa_mdo/structure/dual_beam_mainline/api.py](../src/hpa_mdo/structure/dual_beam_mainline/api.py)
     - [src/hpa_mdo/structure/dual_beam_mainline/solver.py](../src/hpa_mdo/structure/dual_beam_mainline/solver.py)
   - 角色：
     - dual-beam 主線結構求解
     - reaction recovery
     - wire support
   - 性質：
     - 核心 physics / solver 層

2. **Production compare / validation**
   - 位置：
     - [scripts/ansys_dual_beam_production_check.py](../scripts/ansys_dual_beam_production_check.py)
     - [scripts/ansys_crossval.py](../scripts/ansys_crossval.py)
   - 角色：
     - ANSYS compare
     - production baseline 對齊
   - 性質：
     - 驗證與基準資料來源

3. **Smooth evaluator**
   - 角色：
     - 給 manufacturing-aware / discrete workflow 上層調用的平滑評估器
   - 性質：
     - workflow 支撐層

4. **Manufacturing-aware discrete geometry layer**
   - 位置：
     - [scripts/direct_dual_beam_v2m.py](../scripts/direct_dual_beam_v2m.py)
   - 角色：
     - discrete geometry choice
     - manufacturing-aware V2.m++
   - 性質：
     - joint workflow 的 geometry producer

5. **Material proxy layer**
   - 位置：
     - [scripts/direct_dual_beam_v2m_material_proxy.py](../scripts/direct_dual_beam_v2m_material_proxy.py)
     - [src/hpa_mdo/structure/material_proxy_catalog.py](../src/hpa_mdo/structure/material_proxy_catalog.py)
   - 角色：
     - `main_spar_family`
     - `rear_outboard_reinforcement_pkg`
   - 性質：
     - promoted material axis layer

6. **Joint geometry + material workflow**
   - 位置：
     - [scripts/direct_dual_beam_v2m_joint_material.py](../scripts/direct_dual_beam_v2m_joint_material.py)
   - 角色：
     - joint search workflow
     - representative region check
     - decision layer selection
   - 性質：
     - 內部 workflow engine
     - 不是推薦給外部 consumer 直接依賴的入口

7. **Decision interface v1**
   - 位置：
     - output JSON artifact
   - 角色：
     - `Primary / Balanced / Conservative`
     - machine-readable status / fallback reason
   - 性質：
     - 正式給下游 consumer 用的穩定 payload

8. **Producer boundary**
   - 位置：
     - [src/hpa_mdo/producer/joint_decision.py](../src/hpa_mdo/producer/joint_decision.py)
     - [src/hpa_mdo/producer/__main__.py](../src/hpa_mdo/producer/__main__.py)
   - 角色：
     - 對外穩定 CLI / Python API
     - 固定執行 workflow strategy
     - 輸出 decision interface v1
   - 性質：
     - 外部 consumer 應優先使用的 producer 入口

### Equivalent-Beam 目前定位

- `equivalent_beam` 仍然保留在 repo 裡，但目前應視為 **legacy parity / regression 路徑**。
- 它保留的理由是：
  - 保存歷史 Phase I parity 證據
  - 回歸檢查舊的 equivalent internal FEM 假設
  - 幫助辨識 model-form drift
- 它不是目前的：
  - 正式 structural truth
  - dual-beam joint workflow 設計判準
  - jig / inverse-design / hi-fi validation 最終比較基準
  - 推薦給外部 consumer 直接依賴的 producer input

目前正式主線應以 `dual_beam_production`、producer decision interface，以及對應的 dual-beam production / jig artifacts 為準。

## 2. 哪些是 producer，哪些不是

### 正式 producer 層

- `hpa_mdo.producer` Python API
- `python -m hpa_mdo.producer` CLI
- `direct_dual_beam_v2m_joint_material_decision_interface.json`

### 內部 workflow / research 層

- `scripts/direct_dual_beam_v2m_joint_material.py`
- `scripts/direct_dual_beam_v2m_material_proxy.py`
- phase note 文件
- report / summary JSON 裡的研究細節欄位

這些內部層可以在 `hpa-mdo` 內部演進，但不應被外部 consumer 視為穩定 contract。

## 3. consumer 可以依賴哪些輸出

### 推薦正式依賴

- `decision interface json`
  - 檔名：
    - `direct_dual_beam_v2m_joint_material_decision_interface.json`
  - 用途：
    - 給 app / autoresearch / batch reporting 消費

### 可讀但不建議當正式 contract

- `direct_dual_beam_v2m_joint_material_summary.json`
  - 內容很多，但混有研究型診斷資訊
- `direct_dual_beam_v2m_joint_material_report.txt`
  - 人看方便，不適合 machine integration
- `direct_dual_beam_v2m_joint_material_decision_interface.txt`
  - 給人檢查用

## 4. producer 與 consumer 的責任切分

### `hpa-mdo` producer 負責

- 固定跑正式 workflow strategy
- 輸出 decision interface v1
- 維持 schema name / version
- 維持 slot status / fallback reason enum
- 維持 Primary / Balanced / Conservative 三個固定 slot

### 外部 consumer 負責

- 呼叫 producer CLI 或 Python API
- 讀 decision interface JSON
- 依 `schema_name` / `schema_version` 驗證相容性
- 依 `status` / `slot_status` / `fallback_reason_code` 決定下游行為

## 5. 推薦的外部整合方向

第一版最穩的做法是：

1. 外部 consumer 呼叫 `python -m hpa_mdo.producer`
2. 取得 producer manifest
3. 讀 `decision_json_path`
4. 只把 decision interface JSON 當正式 payload

Python API 也可以用，但比較適合同一個 Python 環境內的 notebook / internal tooling / 測試。
