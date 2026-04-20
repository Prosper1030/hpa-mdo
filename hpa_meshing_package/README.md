# hpa-meshing-package

這是一份給 **Codex** 直接接手實作的 package skeleton + implementation brief，目標是把目前「只對少數 special case 可用」的 Gmsh/SU2 前處理流程，升級成可擴展、可維護、可批次執行的 **HPA（human-powered aircraft）自動網格系統**。

## 1. 專案目標

建立一個 Python package `hpa_meshing`，讓使用者只要提供：

- 幾何檔案（STEP/IGES 為主）
- 元件類型（`main_wing` / `tail_wing` / `fairing_solid` / `fairing_vented`）
- meshing policy（尺寸、局部細化、boundary layer、farfield、品質門檻、fallback）

系統就能：

1. 讀取幾何
2. 檢查幾何是否屬於「HPA 可接受」的拓撲家族
3. 自動建立外流場域（farfield）
4. 自動套用該類元件的 meshing recipe
5. 執行 Gmsh 產生 2D/3D mesh
6. 檢查 mesh 品質與 marker/physical groups
7. 輸出 `.su2`、`.msh`、品質報告、log、可選 PNG 截圖
8. 若失敗則依 fallback policy 自動重試

## 2. v1 範圍

### 必做
- `main_wing`
- `tail_wing`
- `fairing_solid`（無洞整流罩）
- `fairing_vented`（有限制的有洞整流罩）

### v1 不做
- 任意髒 CAD 自動修到可網格
- 任意拓撲變更
- 多物件自動裝配（例如整機全機）
- 高度進階 3D viscous mesh「像商業 mesher 那樣幾乎不翻車」
- 複雜 moving mesh / overset / rotating propeller domains

## 3. 設計原則

1. **不是吃任意 CAD**
   - 目標是「任意符合 HPA 設計族的元件」；
   - 不是「任意幾何都要能過」。
2. **先穩定，再通用**
   - 先建立固定拓撲家族的模板化 meshing；
   - 再逐步放寬允許範圍。
3. **先讓 Codex 能驗證**
   - 每個 recipe 都必須可批次測試；
   - 每次執行都要留下 machine-readable report。
4. **對失敗有分類**
   - geometry invalid
   - topology unsupported
   - BL failure
   - volume meshing failure
   - marker mismatch
   - quality gate fail

## 4. 使用者故事

### Story A: 主翼
作為 HPA 設計者，我想把任一支符合規範的主翼 STEP 丟進系統，指定 `main_wing`，系統就能自動建立 farfield、局部前後緣細化、翼尖細化、可選 boundary layer，最後輸出可交給 SU2 的網格。

### Story B: 尾翼
作為 HPA 設計者，我想把任一支尾翼幾何丟進系統，以和主翼相似但較簡化的 recipe 自動出網格。

### Story C: 無洞整流罩
作為 HPA 設計者，我想讓封閉 smooth fairing 自動套用 nose/tail curvature-aware refinement 與近壁策略，穩定產生可跑外流場的網格。

### Story D: 有洞整流罩
作為 HPA 設計者，我想在「有限制的孔洞拓撲」下自動產生 fairing mesh，孔邊可自動細化並保留 marker，若 BL 失敗可降級重試。

## 5. 幾何輸入限制（第一版）

### 通用
- 優先支援 STEP
- 次支援 IGES
- 單一元件，或單一主要實體 + 少數布林孔洞
- 幾何長度單位預設為 meters
- 必須是封閉 solid（v1）
- 不接受裸 STL 當主要工作流（可做未來擴充）

### main_wing / tail_wing
- 單一連續 lifting surface solid
- 不接受分裂成很多片、互相接觸關係不明的 CAD
- 可接受 taper、washout、輕微非平面
- 不要求一定是單一截面規則，但需維持翼類拓撲

### fairing_solid
- 單一封閉 fairing solid
- 無孔
- 表面可光順、可非對稱，但不得自交

### fairing_vented
- 主體仍為單一封閉 fairing solid
- 孔洞數量需低於 recipe 上限
- 每個孔洞需滿足最小曲率半徑與最小間距規則
- 先支援圓孔、橢圓孔、長圓孔、簡單 NACA-like slit
- 暫不支援超細長鋸齒孔、任意自由曲線孔群

## 6. 統一 CLI

```bash
hpa-mesh run \
  --component main_wing \
  --geometry path/to/wing.step \
  --config configs/main_wing.default.yaml \
  --out out/main_wing_case01
```

```bash
hpa-mesh validate-geometry \
  --component fairing_vented \
  --geometry path/to/fairing.step
```

```bash
hpa-mesh batch \
  --manifest cases.yaml \
  --out out/batch_001
```

## 7. 輸出規格

每次 run 至少輸出：

- `mesh.su2`
- `mesh.msh`
- `report.json`
- `report.md`
- `gmsh.log`
- `manifest.resolved.yaml`
- `artifacts/preview.png`（若環境可用）
- `artifacts/surface_tags.json`
- `artifacts/retry_history.json`

## 8. 報告 JSON 範例欄位

```json
{
  "status": "success",
  "component": "main_wing",
  "geometry_file": "wing.step",
  "units": "m",
  "bbox": [0.0, 0.0, 0.0, 12.3, 1.1, 0.24],
  "volume_count": 1,
  "surface_count": 6,
  "recipe": "main_wing_v1",
  "attempts": 2,
  "fallback_actions": [
    "relax_te_refinement",
    "reduce_bl_layers"
  ],
  "mesh_stats": {
    "dimension": 3,
    "num_nodes": 123456,
    "num_elements": 678910
  },
  "quality": {
    "min_jacobian_ok": true,
    "max_skewness_ok": true,
    "negative_volume_count": 0
  },
  "markers": {
    "wall": true,
    "farfield": true,
    "symmetry": false
  }
}
```

## 9. 元件 recipe 概念

### 9.1 main_wing
- 幾何驗證
  - 是否為單一主要實體
  - aspect ratio 合理
  - 厚度非零
- refinement
  - leading edge
  - trailing edge
  - wing tip
  - root/body 接近區（如適用）
- optional BL
- farfield
  - chord/span-aware domain sizing
- quality gates
  - 無負體積
  - marker 完整
  - element count 在限制內

### 9.2 tail_wing
- 與 main_wing 類似，但預設 domain 與 refinement 可更輕量

### 9.3 fairing_solid
- nose curvature refinement
- tail/taper refinement
- 最大曲率區 refinement
- optional wake refinement box downstream
- 可選 BL；若失敗可降級

### 9.4 fairing_vented
- 繼承 `fairing_solid`
- 增加：
  - vent edge refinement
  - vent spacing/topology validation
  - 失敗時優先放寬局部最小尺寸
  - 必要時關閉 BL 改 coarse viscous or inviscid mode

## 10. fallback policy（核心）

這是 package 最重要的部分之一。

### 第一級：局部尺寸放寬
- 孔邊局部尺寸乘上 1.25 ~ 1.5
- trailing edge 最小尺寸略放大
- 過細的曲率自動限幅

### 第二級：boundary layer 降級
- BL 層數減少
- growth ratio 放寬
- total thickness 降低
- 若仍失敗，可切換成 no-BL mode（需在報告中標示）

### 第三級：全域網格放寬
- global min size 調大
- farfield 內部尺寸放寬
- volume algorithm 切換

### 第四級：失敗分類輸出
- 若仍失敗，回傳明確 failure code，不得只吐 raw exception

## 11. package 結構

```text
hpa-meshing-package/
├─ pyproject.toml
├─ README.md
├─ docs/
│  ├─ ARCHITECTURE.md
│  ├─ CODEX_TASK.md
│  ├─ ACCEPTANCE.md
│  └─ OPEN_QUESTIONS.md
├─ configs/
│  ├─ main_wing.default.yaml
│  ├─ tail_wing.default.yaml
│  ├─ fairing_solid.default.yaml
│  └─ fairing_vented.default.yaml
├─ src/hpa_meshing/
│  ├─ __init__.py
│  ├─ cli.py
│  ├─ schema.py
│  ├─ pipeline.py
│  ├─ errors.py
│  ├─ logging_utils.py
│  ├─ geometry/
│  │  ├─ loader.py
│  │  ├─ validator.py
│  │  ├─ topology.py
│  │  └─ features.py
│  ├─ mesh/
│  │  ├─ recipes.py
│  │  ├─ fields.py
│  │  ├─ boundary_layer.py
│  │  ├─ farfield.py
│  │  ├─ quality.py
│  │  └─ export.py
│  ├─ adapters/
│  │  ├─ gmsh_backend.py
│  │  └─ su2_backend.py
│  ├─ reports/
│  │  ├─ json_report.py
│  │  └─ markdown_report.py
│  └─ fallback/
│     └─ policy.py
└─ tests/
   ├─ test_schema.py
   ├─ test_cli.py
   ├─ test_fallback.py
   └─ test_manifest_examples.py
```

## 12. Codex 的工作方式建議

請 Codex **不要直接開始大改亂寫**，而是照這個順序做：

1. 先建立 package skeleton
2. 先做 schema + CLI + report pipeline
3. 先把現有 special case fairing 無洞版包進 `fairing_solid` recipe
4. 再把主翼與尾翼抽象成通用 recipe
5. 最後才做 `fairing_vented`
6. 每完成一階段，都要補 tests 與 example config
7. 每個 fallback 必須可在 log / report 中追蹤

## 13. 第一階段最小可交付（MVP）

必須做到：

- `hpa-mesh run` 可執行
- 可吃 STEP
- `fairing_solid` 可穩定跑通目前已有 special case
- `main_wing` / `tail_wing` 可先對規則幾何跑通
- 成功輸出 `.msh` + `.su2` + `report.json`
- 對失敗案例可輸出 `failure_code`

## 14. 驗收標準（第一版）

### 功能驗收
- 對四類元件各至少 3 個幾何案例可執行
- special case 既有 fairing case 不得退化
- batch mode 可跑多案例

### 工程驗收
- CLI 錯誤訊息明確
- config 能覆寫預設值
- log 與 report 可追溯
- 任何 fallback 動作都必須被記錄

### 通用性驗收
- 修改幾何尺寸後，不需改 Python 原始碼即可重跑
- 修改 config 後，可調整網格細度與 BL 參數
- 不得把 recipe 寫死綁定單一檔名

## 15. 使用上的關鍵假設

這份 package 預設：
- 幾何家族固定在 HPA 元件
- 不追求 CAD 無限通用
- 重點是「可用、可擴展、可批次、可維護」
- 先把現有 special case 提煉成通用規則，再逐步放寬

## 16. 你需要回覆的關鍵開放項

請專案 owner 補充以下資訊，Codex 才能把 recipe 參數收斂得更準：

1. 主翼與尾翼的典型幾何輸入格式：STEP 是否統一？
2. 你們要的第一版是 inviscid 為主，還是一定要 viscous + BL？
3. farfield 大小策略要不要統一，例如：
   - upstream = 5c
   - downstream = 10c~20c
   - normal = 5c~10c
4. fairing 開孔版：
   - 最多幾個孔？
   - 孔型有哪些？
   - 最小孔寬 / 最小孔間距？
5. SU2 邊界命名規範：
   - `wall`
   - `farfield`
   - `symmetry`
   - `inlet` / `outlet` 是否需要？
6. 目前 special case fairing 腳本的輸入輸出契約是什麼？
7. 你們是否需要 2D 截面模式（之後給翼型剖面快速用）？
8. mesh 品質門檻目前有沒有既有標準？

---

這份 repo 的目的不是直接把最難的 meshing 一次做完，而是把你們現在「能跑」的東西，提升成 Codex 可以持續接手、擴充、測試、重構的工程骨架。
