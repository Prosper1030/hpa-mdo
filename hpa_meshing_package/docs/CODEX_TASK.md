# CODEX_TASK.md

## 任務背景

目前 repo 已經能處理一個或少數 **special-case fairing (solid/no-hole)** 幾何，但這不是通用系統。  
目標是把它重構成一個 **可擴展的 HPA meshing package**，支援：

- main wing
- tail wing
- fairing_solid
- fairing_vented

輸入為 HPA family 內的 STEP/IGES 幾何，不要求任意 CAD 通用，但要求：
- 對同類型元件有明確的驗證規則
- 不綁定特定檔名
- 不綁定單一 special-case 幾何

## 對 Codex 的要求

### 1. 先做骨架，不要先優化細節
請先完成：
- `pyproject.toml`
- `src/hpa_meshing/`
- `cli.py`
- `schema.py`
- `pipeline.py`
- `errors.py`
- `reports/`
- `fallback/`
- default configs

### 2. 保留 special-case fairing 成果
請將現有可跑的 fairing 無洞版流程：
- 萃取出可重用部分
- 包裝成 `fairing_solid` recipe
- 保證舊案例仍可運行

### 3. 逐步通用化，不要一次全抽象
推薦順序：
1. fairing_solid
2. main_wing
3. tail_wing
4. fairing_vented

### 4. 一定要留出測試鉤子
即使一開始沒有完整 CAD 測試檔，也要：
- 建立 config parser tests
- 建立 CLI smoke tests
- 建立 fallback policy tests
- 預留 example case manifest

### 5. 記錄所有重試與失敗類型
失敗不能只丟 exception。  
必須分類成：
- `geometry_invalid`
- `topology_unsupported`
- `mesh_generation_failed`
- `boundary_layer_failed`
- `quality_gate_failed`
- `export_failed`

## 第一批任務拆解

### Task 1: package scaffold
- 建立 package 結構
- 補 CLI entrypoint
- 補 schema dataclasses / pydantic models
- 寫 README 中的基本 usage

### Task 2: config + manifest
- 支援單一 run config
- 支援 batch manifest
- 支援 default + override 合併

### Task 3: reporting
- 產生 `report.json`
- 產生 `report.md`
- log retry history

### Task 4: geometry layer
- 用 Gmsh OCC import STEP/IGES
- 建立 bbox / volume_count / surface_count 抽取
- geometry healing hooks（先做 thin wrapper）

### Task 5: fairing_solid recipe
- 把現有流程包成 recipe
- 加入 nose/tail refinement hooks
- 加入 farfield builder
- 支援 export `.msh` + `.su2`

### Task 6: main_wing/tail_wing recipe
- 新增翼類幾何驗證
- 新增前緣/後緣/翼尖 refinement hooks
- 新增 chord/span-aware farfield policy

### Task 7: fairing_vented recipe
- 新增孔洞數量、最小孔寬、最小間距驗證
- 新增孔邊 refinement
- 失敗時優先局部放寬尺寸，再降 BL

### Task 8: tests + docs
- 把所有 CLI 子命令補 smoke tests
- 把 example configs 與 manifest 補齊
- 補 `OPEN_QUESTIONS.md`

## Codex 實作風格要求

- 先讓 code 可跑，再逐步完善
- 每一步都要能在 terminal 驗證
- 不要把 Gmsh calls 分散成不可測的 script soup
- 不要把 geometry validation 和 meshing 完全耦合
- 儘量保留純 Python 層可測部分

## 交付完成條件（第一階段）

當以下條件都成立，第一階段才算完成：

1. `hpa-mesh run --component fairing_solid ...` 可運作
2. `hpa-mesh run --component main_wing ...` 有基本骨架與 example
3. `hpa-mesh run --component tail_wing ...` 有基本骨架與 example
4. `.msh` 與 `.su2` 皆可輸出
5. 任一失敗案例可輸出 `failure_code`
6. 有 `report.json` 和 `retry_history.json`
7. 現有 special-case fairing 不退化
