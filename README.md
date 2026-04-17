# HPA-MDO：人力飛機多學科設計最佳化框架

一套用於人力飛機巡航外形、逆向求形與結構落地的 Python 框架，整合了氣動力載荷解析、inverse design、有限元素分析與 CAE 匯出功能。專為 **Black Cat 004**（翼展 33 m 的人力飛機）而建。

目前這個 repo 的正式主線不是舊的單梁 parity 路線，也不只是 decision producer 包裝層，而是 **`VSP / target cruise shape -> inverse design -> jig shape -> realizable loaded shape -> CFRP / discrete layup`** 這條可持續擴充的工程主線。第一次進 repo 時，請把它當成「可執行的設計引擎 + 正式輸出 contract」，不要把 `equivalent_beam` 或零散研究型 script 當成目前 sign-off 入口。

---

## 你現在應該看哪裡

| 你現在要做什麼 | 先看哪裡 | 為什麼 |
|---|---|---|
| 想先知道「現在真正主線到底是什麼」 | [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md) | 這份是目前正式主線的單一真相文件 |
| 第一次進 repo，想知道怎麼開始 | [README.md](README.md) | 這份就是 landing page，先用它判斷正式入口與第一個指令 |
| 想快速找到所有重要文件 | [docs/README.md](docs/README.md) | 文件索引，會告訴你哪些是正式 contract、哪些是研究/歷史文件 |
| 想知道最近該做什麼、不該先做什麼 | [docs/NOW_NEXT_BLUEPRINT.md](docs/NOW_NEXT_BLUEPRINT.md) | 近期路線圖與優先順序 |
| 想看更細的近期進度與分軌方向 | [docs/EXECUTION_ROADMAP.md](docs/EXECUTION_ROADMAP.md) | 細化版執行路線圖；會告訴你不同卡點應該先推哪條線 |
| 想理解長期願景與五階段藍圖 | [docs/GRAND_BLUEPRINT.md](docs/GRAND_BLUEPRINT.md) | 長期 blueprint，不是日常入口 |

## 三條閱讀路徑

### 第一次使用

1. 先看下面的「安裝方式」與「快速開始」。
2. 跑一次 `python examples/blackcat_004_optimize.py` 或 `python scripts/run_optimization.py --config configs/blackcat_004.yaml`。
3. 如果要理解正式工程主線，再讀：
   - [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md)
   - [docs/dual_beam_workflow_architecture_overview.md](docs/dual_beam_workflow_architecture_overview.md)
   - [docs/NOW_NEXT_BLUEPRINT.md](docs/NOW_NEXT_BLUEPRINT.md)

### 協作開發

- 先以本頁的「目前正式判準」為準，確認不要沿用 legacy parity path。
- 接著讀：
  - [CURRENT_MAINLINE.md](CURRENT_MAINLINE.md)
  - [docs/dual_beam_workflow_architecture_overview.md](docs/dual_beam_workflow_architecture_overview.md)
  - [docs/NOW_NEXT_BLUEPRINT.md](docs/NOW_NEXT_BLUEPRINT.md)
  - [docs/GRAND_BLUEPRINT.md](docs/GRAND_BLUEPRINT.md)

### AI / automation

- 正式對外 machine-readable 入口是 `python -m hpa_mdo.producer` 輸出的 decision interface JSON。
- 如果只需要 consumer contract，請優先讀：
  - [docs/dual_beam_consumer_integration_guide.md](docs/dual_beam_consumer_integration_guide.md)
  - [docs/dual_beam_decision_interface_v1_spec.md](docs/dual_beam_decision_interface_v1_spec.md)
  - [docs/dual_beam_autoresearch_quickstart.md](docs/dual_beam_autoresearch_quickstart.md)

---

## 架構概觀

```
         configs/blackcat_004.yaml         參考 .vsp3（幾何真值）
                   |                              |
                   v                              v
          +-----------------+             +------------------+
          | Config (Pydantic)|  ───────▶  | VSPBuilder       |
          | core/config.py   |            | aero/vsp_builder |
          +-----------------+             +------------------+
                   |                              |
                   v                              v
          +-----------------+             +------------------+
          | VSPAero Parser  |             | Aircraft Builder  |
          | aero/vsp_aero   |             | core/aircraft     |
          +-----------------+             +------------------+
                        \                /
                         v              v
                    +------------------------+
                    |   Load Mapper           |
                    |   aero/load_mapper      |
                    +------------------------+
                                |
                                v
                    +------------------------+
                    |  OpenMDAO FEM Solver    |
                    |  (6-DOF Timoshenko)     |
                    |  structure/oas_struct   |
                    +------------------------+
                                |
                                v
                    +------------------------+
                    |  Spar Optimizer         |  → disp (uz, θy)
                    |  structure/optimizer    |
                    +------------------------+
                        |        |         |
                        v        v         v
          +----------------+  +--------+  +-----------------------+
          | ANSYS Export   |  | Plots  |  | CruiseVSPBuilder       |
          | APDL/CSV/BDF  |  +--------+  | aero/cruise_vsp_builder|
          +----------------+              +-----------------------+
                                                    |
                                                    v
                                          +-----------------+
                                          | vsp_to_cfd.py   |
                                          | STEP / STL      |
                                          +-----------------+
                                                    |
                                                    v
                        [Hi-Fi 驗證層：local structural spot-check]
                               Gmsh → CalculiX → ParaView
                               ASWING（依本機 binary） / SU2（長期）
```

### OpenMDAO Component DAG

```mermaid
graph LR
    DV["設計變數<br/>main_t_seg / rear_t_seg"] --> S2E["SegmentToElementComp"]
    S2E --> DSP["DualSparPropertiesComp<br/>平行軸定理 EI/GJ"]
    DSP --> SB["SpatialBeamComp<br/>6-DOF Timoshenko FEM"]
    SB --> SC["StressComp<br/>von Mises + KS聚合"]
    SC --> OBJ["目標函數<br/>total_mass_full_kg"]
    SC --> C1["約束：failure_index ≤ 0"]
    SB --> C2["約束：twist_max_deg ≤ 2°"]
    SB --> C3["約束：tip_deflection_m ≤ 2.5m"]
```

---

## 功能特色

- **基於 OpenMDAO 的 6-DOF Timoshenko 梁有限元素模型**（SpatialBeam 配方），具解析導數
- **分段碳纖維管設計** -- 11 根管材，每根 3.0 m，半翼展建模為 6 段 [1.5, 3.0, 3.0, 3.0, 3.0, 3.0] m
- **雙梁主線結構分析** -- `dual_beam_mainline` / `dual_beam_production` 是目前正式 structural truth；`equivalent_beam` 只保留為 legacy parity / regression 路徑
- **升力鋼索支撐** -- 在鋼索連接接頭位置施加垂直撓度約束條件
- **VSPAero 整合** -- 解析 `.lod`（展向載荷）與 `.polar`（積分係數）輸出檔案
- **ANSYS APDL / Workbench CSV / NASTRAN BDF 匯出** -- 自動生成用於獨立有限元驗證的輸入檔案
- **FastAPI + MCP 伺服器**，用於 AI 代理整合（Claude Code、遠端批次作業、網頁儀表板）
- **代理模型訓練資料收集** -- 將設計評估結果寫入 CSV 供機器學習模型訓練
- **獨立的安全係數** -- `aerodynamic_load_factor` 用於載荷，`material_safety_factor` 用於容許應力（永不混用）
- **外部材料資料庫** -- 所有材料屬性以鍵值方式從 `data/materials.yaml` 載入

---

## 目前正式判準

這個 repo 目前有兩條容易混淆的結構路線，請以這裡為準：

- **正式 structural truth / 設計判準**：`src/hpa_mdo/structure/dual_beam_mainline/` 的 `dual_beam_production` 模式，以及其上游的 joint workflow / producer 輸出。
- **正式對外 consumer contract**：`python -m hpa_mdo.producer` 產出的 decision interface JSON。
- **legacy parity path**：`equivalent_beam` 與 `scripts/ansys_crossval.py --export-mode equivalent_beam` 只保留為歷史 Phase I parity / regression 參考，不應再當成目前的設計 sign-off、排名基準或高保真比對目標。
- **高保真幾何/驗證目標**：應優先對齊 dual-beam production / inverse-design artifacts，例如 production check report、selected design summary、`spar_jig_shape.step`、loaded-shape artifacts；不要預設拿 `output/blackcat_004/optimization_summary.txt` 或 `spar_model.step` 當最後真值。

如果你是人或 AI 代理，對 Black Cat 004 的後續開發請優先讀：

- [docs/dual_beam_workflow_architecture_overview.md](docs/dual_beam_workflow_architecture_overview.md)
- [docs/dual_beam_consumer_integration_guide.md](docs/dual_beam_consumer_integration_guide.md)
- [docs/GRAND_BLUEPRINT.md](docs/GRAND_BLUEPRINT.md)

---

## 安裝方式

需要 Python 3.10 以上版本。相容 Mac（Apple Silicon / Intel）及 Windows。

```bash
git clone https://github.com/Prosper1030/hpa-mdo.git
cd hpa-mdo
uv venv --python 3.10 .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS
uv pip install -e ".[all]"
```

選用相依套件群組：

| 群組 | 套件 | 用途 |
|------|------|------|
| `oas` | openaerostruct, openmdao | 有限元素求解器（最佳化必要） |
| `api` | fastapi, uvicorn | REST API 伺服器 |
| `mcp` | mcp | 供 AI 代理使用的 Model Context Protocol |
| `cad` | cadquery | STEP 幾何匯出 |
| `dev` | pytest, pytest-cov, ruff | 開發與測試 |
| `all` | 以上全部 | 完整安裝 |

使用 `pip install -e ".[oas,api]"` 安裝部分群組。

### 跨平台路徑設定

外部 VSPAero / OpenVSP / 翼型檔案路徑請放在 `configs/local_paths.yaml`，不要直接改主配置檔。

```bash
cp configs/local_paths.example.yaml configs/local_paths.yaml
```

`configs/blackcat_004.yaml` 只保留相對於 `io.sync_root` 的外部資料路徑，因此同一份工程配置可以在 Windows 與 macOS 共用。

---

## 快速開始

對 Black Cat 004 配置執行完整最佳化流程：

```bash
python examples/blackcat_004_optimize.py
```

或使用配置旗標模式：

```bash
python scripts/run_optimization.py --config configs/blackcat_004.yaml
```

執行後將會：
1. 載入 YAML 配置並建立飛機模型
2. 解析 VSPAero 氣動力資料（`.lod` 檔）
3. 將氣動力載荷對應至結構梁節點，並依實際飛行條件重新量綱化
4. 最佳化各段管壁厚度以最小化翼梁質量
5. 將結果匯出為 ANSYS 格式並儲存圖表

stdout 的最後一行永遠為 `val_weight: <float>`（最佳化後全翼展翼梁系統質量，單位 kg），作為上游 AI 代理迴圈的目標函數值。

### 用你自己的 VSP 試跑（Generic VSP intake）

只要 `.vsp3` 遵循「主翼（XZ 對稱）＋ 水平尾（XZ 對稱）＋ 垂直尾」的標準
慣例，可以直接讓管線自動抽幾何、產 config、跑最佳化，不用手改 YAML：

```bash
python scripts/analyze_vsp.py --vsp path/to/any.vsp3
```

搭配選項：

- `--no-run`：只產 `output/<vsp_stem>/resolved_config.yaml`，不跑求解器。
- `--template configs/my.yaml`：用自己的工程參數模板（預設沿用
  `configs/blackcat_004.yaml` 的材料、安全係數、翼梁分段）。
- `--dump-summary out.json`：把 VSP 解析結果落地成 JSON 供偵錯。

辨識規則見 `src/hpa_mdo/aero/vsp_introspect.py`；完整 Phase 1 限制與
Phase 2 計畫見 `docs/hi_fidelity_validation_stack.md`。

---

## Dual-Beam Decision Producer

如果外部系統只需要 dual-beam joint workflow 的正式 decision output，現在建議不要直接碰研究型 script。

正式 producer 入口：

```bash
uv run python -m hpa_mdo.producer --output-dir /abs/path/to/run_dir
```

正式 consumer payload：

- `direct_dual_beam_v2m_joint_material_decision_interface.json`

相關文件：

- [workflow / architecture overview](docs/dual_beam_workflow_architecture_overview.md)
- [decision interface v1 spec](docs/dual_beam_decision_interface_v1_spec.md)
- [consumer integration guide](docs/dual_beam_consumer_integration_guide.md)
- [built-in autoresearch quickstart](docs/dual_beam_autoresearch_quickstart.md)

---

## Built-In Autoresearch Consumer

現在 repo 內已經內建一個第一版最小 consumer / autoresearch 入口：

```bash
uv run python -m hpa_mdo.autoresearch --output-dir /abs/path/to/run_dir
```

或：

```bash
uv run hpa-autoresearch --output-dir /abs/path/to/run_dir
```

這個第一版入口只做一件事：

- 呼叫正式 producer：`python -m hpa_mdo.producer`
- 讀 decision interface v1 JSON
- 只吃 `Primary design`
- 固定 score：`-Primary.mass_kg`

stdout 會輸出 machine-readable-friendly 的摘要資訊，以及最後一行：

```text
分數: -10.089649
```

目前還**沒有**做：

- Balanced / Conservative 混合評分
- 多目標 decision
- 大型 agent orchestration / batch platform
- 更高階的 search strategy

相關文件：

- [built-in autoresearch quickstart](docs/dual_beam_autoresearch_quickstart.md)

---

## 專案結構

```
hpa-mdo/
  configs/
    blackcat_004.yaml          # 主要飛機配置檔
    local_paths.example.yaml   # 各機器的外部資料根目錄範例
  data/
    materials.yaml             # 材料屬性資料庫
  database/
    training_data.csv          # 代理模型訓練樣本
  examples/
    blackcat_004_optimize.py   # 端對端最佳化範例
  output/
    blackcat_004/              # 結果、圖表、ANSYS 匯出檔
  src/hpa_mdo/
    autoresearch/
      consumer.py              # 第一版內建 consumer：Primary-only score = -mass
      __main__.py              # `python -m hpa_mdo.autoresearch` CLI
    core/
      config.py                # Pydantic 綱要（完全對應 YAML 結構）
      aircraft.py              # 機翼幾何、飛行條件、翼型資料
      materials.py             # MaterialDB 載入器（外部 YAML）
    aero/
      base.py                  # SpanwiseLoad 資料類別、AeroParser 抽象基底類別
      vsp_aero.py              # VSPAero .lod/.polar 解析器
      xflr5.py                 # XFLR5 解析器（替代方案）
      load_mapper.py           # 氣動力至結構載荷內插
    structure/
      spar.py                  # TubularSpar 幾何建構器
      spar_model.py            # 管截面屬性、雙翼梁數學
      oas_structural.py        # OpenMDAO Timoshenko 梁元件
      optimizer.py             # SparOptimizer（OpenMDAO + scipy 備援）
      ansys_export.py          # APDL、Workbench CSV、NASTRAN BDF 寫入器
    fsi/
      coupling.py              # 單向與雙向流固耦合
    api/
      server.py                # FastAPI REST 端點
      mcp_server.py            # 供 AI 代理工具使用的 MCP 伺服器
    producer/
      joint_decision.py        # 對外穩定 dual-beam decision producer API
      __main__.py              # 對外穩定 dual-beam decision producer CLI
    utils/
      cad_export.py            # STEP 匯出核心工具
      visualization.py         # Matplotlib 繪圖工具
  tests/
  pyproject.toml               # 建置配置、相依套件
```

---

## 配置說明

所有工程參數均定義於 `configs/blackcat_004.yaml`。配置於載入時由 `core/config.py` 中的 Pydantic 綱要驗證。

### 主要區段

**`flight`** -- 用於載荷重新量綱化的巡航條件。
```yaml
flight:
  velocity: 6.5        # 巡航真空速 [m/s]
  air_density: 1.225    # ISA 海平面 [kg/m^3]
```

**`safety`** -- 載荷與材料的獨立安全係數。
```yaml
safety:
  aerodynamic_load_factor: 2.0   # 設計極限載荷係數 [G]
  material_safety_factor: 1.5    # 極限抗拉強度折減係數
```

**`wing`** -- 翼面幾何、翼型定義與扭轉角約束條件。
```yaml
wing:
  span: 33.0
  root_chord: 1.30         # VSP-calibrated（原 1.39）
  tip_chord: 0.435         # VSP-calibrated（原 0.47）
  max_tip_twist_deg: 2.0   # 扭轉角約束條件
```

> **幾何真值**：`configs/blackcat_004.yaml` 的 `wing.root_chord` 與
> `wing.tip_chord` 只存「端點極值」。完整翼展 chord / dihedral 排程由
> `io.vsp_model` 指向的參考 `.vsp3` 讀取（含 y=0→4.5 m 等弦內段），由
> `VSPBuilder._wing_section_schedule()` 優先採用。執行
> `python scripts/vsp_consistency_check.py` 會檢查三份記錄是否一致：
> 參考 `.vsp3`、`configs/*.yaml`、`data/*.avl` 檔頭 `Sref/Cref/Bref`。

**`main_spar` / `rear_spar`** -- 分段管材定義。`segments` 列表定義半翼展管材長度（翼根至翼尖）。`material` 鍵值對應 `data/materials.yaml`。
```yaml
main_spar:
  material: "carbon_fiber_hm"
  segments: [1.5, 3.0, 3.0, 3.0, 3.0, 3.0]   # 總和 = 16.5 m 半翼展
  min_wall_thickness: 0.8e-3                     # 製造下限 [m]
```

**`lift_wires`** -- 鋼索連接位置（必須與接頭位置重合）。
```yaml
lift_wires:
  attachments:
    - { y: 7.5, fuselage_z: -1.5, label: "wire-1" }
```

**`solver`** -- 有限元素離散化與最佳化器設定。
```yaml
solver:
  n_beam_nodes: 60
  optimizer: "SLSQP"
  fsi_coupling: "one-way"
```

**`io`** -- VSPAero 資料、翼型座標及輸出目錄的檔案路徑。外部資料檔請以 `sync_root + 相對路徑` 的方式管理，本機差異放在 `configs/local_paths.yaml`。

```yaml
io:
  sync_root: null
  vsp_lod: "Aerodynamics/black cat 004 wing only/blackcat 004 wing only_VSPGeom.lod"
  airfoil_dir: "Aerodynamics/airfoil"
  output_dir: "output/blackcat_004"
```

---

## API 使用方式

### FastAPI REST 伺服器

啟動伺服器：

```bash
uvicorn hpa_mdo.api.server:app --host 0.0.0.0 --port 8000 --reload
```

或透過已安裝的進入點：

```bash
hpa-mdo
```

端點範例：

```bash
# 健康狀態檢查
curl http://localhost:8000/health

# 列出材料
curl http://localhost:8000/materials

# 執行最佳化（POST）
curl -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{"config_yaml_path": "configs/blackcat_004.yaml", "aoa_deg": 3.0}'

# 匯出 ANSYS / NASTRAN / CSV
curl -X POST http://localhost:8000/export \
  -H "Content-Type: application/json" \
  -d '{"config_yaml_path": "configs/blackcat_004.yaml", "output_dir": "output/blackcat_004/ansys", "formats": ["apdl", "csv", "nastran"]}'
```

### MCP 伺服器（供 AI 代理使用）

新增至 Claude Code 的 MCP 配置：

```json
{
  "mcpServers": {
    "hpa-mdo": {
      "command": "python",
      "args": ["-m", "hpa_mdo.api.mcp_server"]
    }
  }
}
```

可用的 MCP 工具：

| 工具 | 說明 |
|------|------|
| `list_materials` | 列出資料庫中的所有材料 |
| `parse_vspaero` | 解析 `.lod` 檔並回傳展向載荷分佈 |
| `optimize_spar` | 從配置與氣動力資料執行完整翼梁最佳化 |
| `export_ansys` | 最佳化並匯出為 APDL、CSV 及/或 NASTRAN 格式 |
| `beam_analysis` | 評估特定設計點而不執行最佳化 |

---

## 供 AI 代理使用

本框架專為自動化最佳化迴圈而設計。每次成功執行後會輸出最終一行：

```
val_weight: <float>
```

其中 `<float>` 為最佳化後全翼展翼梁系統質量（單位：公斤）。若求解器失敗或結果不符合物理，此值為 `99999`。上游代理應解析此值作為最小化的目標函數。

設計變數為 12 段管壁厚度（每根翼梁 6 段，共 2 根翼梁）。約束條件為應力比（failure_index <= 0）、翼尖扭轉角（<= 2 度）及撓度。最佳化器採用兩階段策略：差分演化法進行全局搜尋，再以 SLSQP 進行局部精修。

---

## 幾何管線（Reference VSP → Jig → Cruise → CFD）

```
參考 .vsp3（原始設計，幾何真值）
  │  VSPBuilder._wing_section_schedule()
  ▼
雙梁結構模型（jig shape）
  │  OpenMDAO FEM 求解 → disp (nn, 6) = [ux, uy, uz, θx, θy, θz]
  ▼
自動調整上反角 / 翼梁壁厚
  │  CruiseVSPBuilder(cfg, y, uz, θy)
  ▼
cruise.vsp3（巡航下的變形外型）
  │  scripts/vsp_to_cfd.py
  ▼
STEP / STL → CFD（或轉交高保真驗證層）
```

相關指令：

```bash
# 完整 MDO（jig 最佳化 + 輸出 optimized jig STEP）
python examples/blackcat_004_optimize.py

# 幾何三者一致性檢查（參考 .vsp3 vs YAML vs AVL）
python scripts/vsp_consistency_check.py

# 由 .vsp3 轉檔給 CFD（STEP / STL / IGES / OBJ / DXF）
python scripts/vsp_to_cfd.py \
    --vsp output/blackcat_004/cruise.vsp3 \
    --out output/blackcat_004/cruise \
    --formats step stl
```

---

## 高保真驗證層（Apple Silicon Mac mini）

為了把最後一哩驗證盡量留在同一台機器上，不再每次切到 Windows 跑 ANSYS，
repo 內已經有一條本機 structural high-fidelity 路線：

`summary -> STEP -> Gmsh -> CalculiX -> report / ParaView`

它目前的定位是 **local structural spot-check**，不是最終真值，也不該直接拿來背書 discrete layup 或完整 aeroelastic sign-off（詳見 [`docs/hi_fidelity_validation_stack.md`](docs/hi_fidelity_validation_stack.md)）。

| 層 | 工具 | 角色 | 狀態 |
|----|------|------|------|
| 結構 | **Gmsh** | STEP→網格（`.inp`） | 已有 runner / script，仍在收斂 mesh contract |
| 結構 | **CalculiX (ccx)** | static / buckle solver | 已有 runner / report，現階段主要做 structural spot-check |
| 後處理 | **ParaView** | 結構 (`.frd`) 視覺化 | 已有 `pvpython` script generator |
| 非線性氣動彈 | **ASWING** | trim / nonlinear aeroelastic | glue 已有，是否可跑取決於本機 binary |
| 氣動 CFD | **SU2** | RANS / Euler CFD | 長期藍圖，不是近期 blocker |

呼叫時機：**主最佳化迴圈不觸發高保真層**，只在使用者手動驗證時透過
獨立 script 啟動，且所有 binary 路徑從 `configs/local_paths.yaml` 覆
蓋，維持跨機器可攜。近期比較合理的做法，是先把它收斂成可信的本機 structural spot-check，再逐步擴大驗證範圍。

---

## 目標飛機

**Black Cat 004** 是一架具有下列規格的人力飛機：

- 翼展 33.0 m
- 操作重量 96 kg（機體 40 kg + 飛行員 56 kg）
- 海平面巡航速度 6.5 m/s
- 翼根翼型 Clark Y SM，翼尖翼型 FX 76-MP-140
- 漸進式上反角（0 至 6 度）
- 主翼梁位於 25% 弦長處，後翼梁位於 70% 弦長處
- 高模量碳纖維管（Toray M46J 等級，E = 230 GPa）
- 升力鋼索位於翼展 7.5 m 位置

---

## 授權條款

MIT
