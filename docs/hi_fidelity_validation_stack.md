# 高保真分析層藍圖（Apple Silicon Mac mini）

> 狀態：**藍圖 / 預留介面**。目前程式碼尚未實作對應連結；本文件定義
> 目標架構、資料流與介面契約，讓後續實作不需要再討論整體方向。

## 動機

MDO 迴圈內部使用 OpenMDAO 6-DOF Timoshenko 梁 + VSPAero VLM，屬於
**中保真度**，用來在設計空間內快速收斂。真正決定是否投入製造的**最後一哩驗證**，目前仰賴 ANSYS Workbench / Fluent，必須切到 Windows
工作站操作，節奏被迫中斷。

本層的目的：**把最終驗證留在同一台 Apple Silicon Mac mini 上**，以
開源工具鏈取代 ANSYS 的最終驗證角色，讓「MDO 收斂 → 高保真檢查 →
回饋」的迴圈在一台機器上完成。

## 工具選型

### A. 結構分析層（實作優先）

| 工具 | 角色 | 二進位來源（Apple Silicon） |
|------|------|------------------------------|
| **Gmsh** | 幾何→網格自動生成器。吃 `CruiseVSPBuilder` 輸出的 STEP，輸出 `.inp` / `.msh` | `brew install gmsh`（arm64 原生） |
| **CalculiX (ccx + cgx)** | 非線性靜力 / 挫曲 solver，輸入 `.inp` 輸出 `.frd` | `brew install calculix-ccx`；MacPorts 亦可 |
| **ParaView** | 統一後處理。讀 `.frd`（CalculiX）、`.vtu`（SU2）、甚至 `.lod` 轉出的 vtk | [paraview.org](https://www.paraview.org/download) 官方 arm64 dmg |

### B. 氣動分析層（藍圖，暫不實作）

| 工具 | 角色 | 備註 |
|------|------|------|
| **SU2** | RANS / Euler CFD，讀 STL 或 CGNS 網格 | 僅保留設定檔模板與資料流藍圖；實際 compile 與驗證延後 |

## 介面契約

### 資料流

```
                ┌───────────────────┐
                │ 參考 .vsp3 (jig)   │  ← 幾何真值
                └─────────┬─────────┘
                          ▼
             ┌───────────────────────────┐
             │ VSPBuilder.build_vsp3()   │
             └─────────┬─────────────────┘
                       ▼
        ┌──────────────────────────────────┐
        │ OpenMDAO FEM → disp (nn, 6)      │   ← 中保真
        └─────────┬────────────────────────┘
                  ▼
   ┌─────────────────────────────────────────┐
   │ CruiseVSPBuilder(uz, θy) → cruise.vsp3  │
   └─────────┬────────────────────┬──────────┘
             ▼                    ▼
┌──────────────────────┐  ┌──────────────────────┐
│ vsp_to_cfd.py        │  │ vsp_to_cfd.py        │
│  → jig.step          │  │  → cruise.step/stl   │
└─────────┬────────────┘  └─────────┬────────────┘
          ▼                         ▼
    ┌──────────────┐          ┌──────────────┐
    │ Gmsh         │          │ Gmsh (藍圖)   │ ← SU2 CFD
    │  → .inp      │          │  → .cgns     │
    └──────┬───────┘          └──────┬───────┘
           ▼                         ▼
    ┌──────────────┐          ┌──────────────┐
    │ CalculiX     │          │ SU2  (藍圖)   │
    │  → .frd      │          │  → .vtu      │
    └──────┬───────┘          └──────┬───────┘
           └───────────┬─────────────┘
                       ▼
                ┌──────────────┐
                │ ParaView     │
                └──────────────┘
```

### 路徑宣告

所有高保真工具的二進位與輸出路徑透過 `configs/blackcat_004.yaml` 的
`hi_fidelity` 區段宣告，機器差異放在 `configs/local_paths.yaml`
（與 `io.sync_root` 同一套機制）。預設每個工具 `enabled: false`，呼叫時若未啟用就直接跳過並印出 INFO。

```yaml
hi_fidelity:
  gmsh:
    enabled: false
    binary: null            # e.g. /opt/homebrew/bin/gmsh
    mesh_size_m: 0.05
  calculix:
    enabled: false
    ccx_binary: null        # e.g. /opt/homebrew/bin/ccx
    cgx_binary: null
  paraview:
    enabled: false
    binary: null            # e.g. /Applications/ParaView.app/Contents/MacOS/paraview
  su2:
    enabled: false          # 藍圖階段；真的要跑 CFD 再打開
    binary: null
    cfg_template: null      # 指向 SU2 .cfg 模板
```

### 模組介面（未實作，僅定義形狀）

- `hpa_mdo.hifi.gmsh_runner.mesh_from_step(step_path, cfg) -> Path`
  - 吃 STEP 檔，跑 Gmsh CLI 生 `.inp`（CalculiX 專用格式），回傳路徑。失敗不丟 exception，回 `None` + 記 INFO。
- `hpa_mdo.hifi.calculix_runner.run_buckling(inp_path, cfg) -> dict`
  - 吃 `.inp` 執行 BUCKLE step，解析 `.frd` 取第一特徵值，回傳 `{"lambda_1": float, "frd_path": Path}`。
- `hpa_mdo.hifi.paraview_state.make_pvsm(frd_paths, vtu_paths) -> Path`
  - 產生 ParaView state 檔讓使用者一鍵開啟全部結果。
- `hpa_mdo.hifi.su2_runner.run_rans(stl_path, cfg) -> dict`（**藍圖**）
  - 吃 STL + 模板，寫 SU2 `.cfg`，跑 CFD，回傳 Cl/Cd/Cm 與 `.vtu` 路徑。**未實作**。

### 呼叫時機

主最佳化迴圈 **不** 呼叫這些工具；它們只在**驗證**階段由使用者或獨立 script 觸發：

```bash
# 1. 先跑 MDO 得到 jig + cruise VSP
python examples/blackcat_004_optimize.py

# 2. 轉成 STEP
python scripts/vsp_to_cfd.py --vsp output/blackcat_004/cruise.vsp3 \
    --out output/blackcat_004/cruise --formats step stl

# 3. 結構驗證（規劃中）
python scripts/hifi_structural_check.py --config configs/blackcat_004.yaml

# 4. 開 ParaView 看結果（規劃中）
```

## 實作順序

1. **M-HF1**：Gmsh runner（STEP → .inp），最小可跑通。
2. **M-HF2**：CalculiX runner（線性靜力，對比 OpenMDAO FEM 的翼尖位移）。
3. **M-HF3**：CalculiX BUCKLE step（驗證 OpenMDAO 殼式挫曲安全因子）。
4. **M-HF4**：ParaView state generator。
5. **M-HF5**（藍圖，不排時程）：SU2 RANS pipeline，對比 VSPAero。

每個里程碑都必須：
- 保持 `val_weight: 99999` 的失敗協定（工具找不到 / 回報錯誤都不得讓主流程崩潰）。
- 所有路徑與數值閾值從 `cfg.hi_fidelity.*` 讀，不得硬編碼。
- 新增 `tests/test_hifi_*.py` 的 stub，在未安裝工具時 `pytest.skip`。

## 通用 VSP 輸入（Generic VSP intake）

目的：任何符合「**主翼 + 水平尾 + 垂直尾**」慣例的 `.vsp3` 都能被分析，
使用者不用改 YAML 幾何欄位。

### 使用方式

```bash
# 最簡用法 — 指定 .vsp3，其他從 configs/blackcat_004.yaml 繼承工程參數
python scripts/analyze_vsp.py --vsp path/to/any.vsp3

# 只想檢查解析結果不跑最佳化
python scripts/analyze_vsp.py --vsp path/to/any.vsp3 --no-run

# 換成自己的工程參數模板
python scripts/analyze_vsp.py --vsp path/to/any.vsp3 \
    --template configs/my_hpa.yaml
```

輸出會落在 `output/<vsp_stem>/`：
- `resolved_config.yaml`：合併後的完整設定檔（幾何來自 VSP，其他來自模板）。
- 其餘與 `blackcat_004_optimize.py` 相同（`beam_analysis.png`、
  `spar_geometry.png`、`wing_jig.vsp3`、`wing_cruise.vsp3` 等）。

### 慣例與辨識規則

`src/hpa_mdo/aero/vsp_introspect.py` 依序嘗試：

1. **名稱比對**（normalize 後）：`main / mainwing / wing` → 主翼；
   `elevator / htail / hstab / tailplane` → 水平尾；
   `fin / vtail / vstab / rudder / verticalfin` → 垂直尾。
2. **對稱性與尺寸啟發式**：最大 XZ 對稱 WING geom = 主翼；第二大 = 水平尾；
   非對稱且 x 旋轉 ≈ 90° 的 WING geom = 垂直尾。

若啟發式失敗（例如全部用同一個名字），請先 rename 每個 geom 再試。

### 目前限制（Phase 1）

- 只抽幾何（span / root / tip chord / 位置 / 旋轉）。翼型檔（AFILE）、
  控制面偵測、dihedral schedule 的變化仍需手動維護在模板中。
- VSPAero 的 `.lod` / `.polar` 必須與 `.vsp3` 在同一個資料夾，檔名遵循
  OpenVSP 預設 `<stem>_VSPGeom.lod` / `_VSPGeom.polar`。
- 翼段（segment lengths）由模板繼承，並不隨 span 自動縮放 — 若新機的
  span 與模板差太多，需要手動調整 `main_spar.segments`。

詳細 Phase 2 計畫見 `docs/codex_prompts/M_VSP2_generic_intake_phase2.md`。

## 高保真驗證層參考資料清單

實作 M-HF1 ~ M-HF5 需要搜集的官方文件與教學，依優先度排序：

### P0 — 一定要讀（實作前）

| 主題 | 來源 | 用途 |
|------|------|------|
| CalculiX User's Manual v2.22 | [官方 PDF](http://www.dhondt.de/ccx_2.22.pdf) | `.inp` 語法，特別是 `*STATIC` / `*BUCKLE` / `*CLOAD` / `*BOUNDARY` / `*NODE FILE` 關鍵字。 |
| Gmsh Reference Manual | [gmsh.info/doc](https://gmsh.info/doc/texinfo/gmsh.html) | Geo / Python API 的 `MeshSizeMax`、Physical Group、`-format inp` 匯出。 |
| OpenVSP API Reference | [openvsp.org/api_docs/latest](http://www.openvsp.org/api_docs/latest/) | `SetDriverGroup`、`InsertXSec`、`ExportFile` 的精確 enum 值。 |

### P1 — 驗證階段需要（跑 golden test 時對照）

| 主題 | 來源 | 用途 |
|------|------|------|
| Dhondt CalculiX 教學範例集 | [dhondt.de/ccx_2.22.test.tar.bz2](http://www.dhondt.de/) | 官方 regression test 的 `.inp`，可以拿來做 golden compare。 |
| NASA SP-8007 Buckling of Thin-Walled Circular Cylinders | NASA TRS | 我們薄殼挫曲公式的來源，跟 CalculiX `*BUCKLE` 特徵值比對時必讀。 |
| ParaView Python Scripting Guide | [docs.paraview.org](https://docs.paraview.org/en/latest/ReferenceManual/pythonAndBatchPvpythonAndPvbatch.html) | M-HF4 state generator 要用 `pvsm` 或 `.py` batch script。 |
| MIT Daedalus flight test data | Bussolari & Nadel 1989 AIAA | 翼尖撓度、扭轉、重量 benchmark 對照。 |

### P2 — CFD 藍圖階段再讀（SU2 延後實作）

| 主題 | 來源 | 用途 |
|------|------|------|
| SU2 Tutorials — Inviscid Wing | [su2code.github.io/tutorials](https://su2code.github.io/tutorials/Inviscid_ONERAM6/) | 低雷諾數 HPA 翼面 RANS 起手式。 |
| SU2 Config File Reference | [su2code.github.io/docs_v7](https://su2code.github.io/docs_v7/Physical-Definition/) | 設定檔關鍵字、邊界條件、solver 類型。 |
| Drela low-Re airfoil papers | MIT OCW / AIAA | 低雷諾數機翼的 transition model 取捨。 |

### 使用者搜集建議

請用下面的順序準備：

1. **下載 CalculiX 2.22 manual PDF** 放到 `docs/reference/` 下（已加入 `.gitignore` 白名單）。
2. **clone CalculiX test cases**（約 500 MB，不 commit，放在 `/Volumes/Samsung SSD/reference/calculix_tests/`）。
3. **存一份 Daedalus 翼尖撓度/重量表**（手動 copy from paper → `docs/reference/daedalus_benchmarks.md`）。
4. ParaView 與 SU2 的文件是 online 查詢即可，不用在本機備存。

## 非目標

- **不取代** MDO 迴圈內的中保真 solver。Gmsh + CalculiX 是驗證，不是最佳化內層。
- **不包裝 GUI**。ParaView state 是選配，使用者仍可直接開原始 `.frd` / `.vtu`。
- **不處理 Windows 平台**。本層鎖定 Apple Silicon；Windows 工作站繼續用 ANSYS 匯出路徑。
