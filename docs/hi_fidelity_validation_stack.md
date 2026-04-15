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

## 非目標

- **不取代** MDO 迴圈內的中保真 solver。Gmsh + CalculiX 是驗證，不是最佳化內層。
- **不包裝 GUI**。ParaView state 是選配，使用者仍可直接開原始 `.frd` / `.vtu`。
- **不處理 Windows 平台**。本層鎖定 Apple Silicon；Windows 工作站繼續用 ANSYS 匯出路徑。
