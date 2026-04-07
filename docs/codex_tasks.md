# HPA-MDO 專案 Review 與優化清單

> 產出日期：2026-04-07｜基於完整原始碼靜態分析

## 整體評價

架構乾淨、config 管理嚴謹、安全係數分離正確、跨平台 path 處理良好。**主要缺口在於 FSI 模組壞掉、測試覆蓋率極低、缺乏 logging/CI**，不是架構問題。總計約 6,052 行 Python，26 個模組。

---

## P0｜必修缺陷（Bug / Broken Code）

### 1. `fsi/coupling.py` 完全壞掉

- **位置**：`src/hpa_mdo/fsi/coupling.py` 第 28-30 行
- **問題**：import 了不存在的 `hpa_mdo.structure.beam_model`（`EulerBernoulliBeam`、`BeamResult`），模組一 import 即崩潰
- **任務**：
  - 移除 dead imports
  - 改為 import 現行 `oas_structural` 介面
  - 重寫 `FSICoupling.run_one_way()` 走 OpenMDAO 路徑
  - 為 two-way FSI 加上「依賴 VSP Python API」的執行時檢查；XFLR5 路徑直接 `raise NotImplementedError`
- **驗收**：`python -c "from hpa_mdo.fsi.coupling import FSICoupling"` 不拋例外

---

### 2. 違反 CLAUDE.md 鐵律之硬編碼

- **位置**：`src/hpa_mdo/core/aircraft.py` 第 139-140 行
  ```python
  tc_root, tc_tip = 0.117, 0.140  # Clark Y SM, FX 76-MP-140
  ```
- **任務**：
  - 將厚弦比移到 `configs/blackcat_004.yaml`：新增 `wing.airfoil_root_tc: 0.117` 與 `wing.airfoil_tip_tc: 0.140`
  - 同步更新 `core/config.py` 的 `WingConfig` Pydantic 模型
  - `aircraft.py` 改為從 config 讀取
- **驗收**：`python -c "from hpa_mdo.core.config import load_config; c = load_config('configs/blackcat_004.yaml'); assert c.wing.airfoil_root_tc == 0.117"`

---

### 3. `data_collector.py` 寫死段數 `_N_SEG = 6`

- **位置**：`src/hpa_mdo/utils/data_collector.py`
- **問題**：與其他 segment 數量的 config 不相容，會 silent NaN padding
- **任務**：改為從 config 動態讀取 `len(spar.segments)`，欄位名稱加上索引（`main_t_seg_1` ... `main_t_seg_N`）
- **驗收**：以不同 segments 長度的 config 建立 `DataCollector` 不報錯，CSV 欄位數正確

---

### 4. `LoadMapper.map_loads()` 缺少數值驗證

- **位置**：`src/hpa_mdo/aero/load_mapper.py`
- **任務**：對輸入 `SpanwiseLoad` 加 NaN/Inf 檢查、負弦長（chord ≤ 0）檢查；失敗時 raise `ValueError`，讓上層走 `val_weight: 99999` 路徑
- **驗收**：傳入含 NaN 的假 SpanwiseLoad 能觸發 ValueError

---

## P1｜測試補強

> 目前只有 2 個檔案、4 個測試。

### 5. 補齊 unit tests

建立以下測試檔案，每個至少 3-5 個 test case：

| 檔案 | 涵蓋範圍 |
|------|---------|
| `tests/test_vspaero_parser.py` | header 變體、多 AoA case 切分、缺欄位容錯 |
| `tests/test_xflr5_parser.py` | 欄位名彈性、CSV 編碼 |
| `tests/test_load_mapper.py` | 重新量綱化正確性、cubic spline 對齊、`aerodynamic_load_factor` 僅套用一次 |
| `tests/test_dual_spar_section.py` | 平行軸定理對稱情境的解析解比對 |
| `tests/test_materials_db.py` | MaterialDB 鍵值載入、缺鍵 raise `KeyError` |

---

### 6. Integration test

- **新建**：`tests/test_blackcat_pipeline.py`
- **內容**：跑迷你版（`n_beam_nodes=20`、`maxiter=5`）full pipeline（config → parse → map → optimize → export）
- **驗收**：`val_weight` 為合理範圍（< 99999）且 `failure_index <= 0`

---

### 7. OpenMDAO check_partials

- **新建**：`tests/test_partials.py`
- **內容**：對 `SegmentToElementComp`、`DualSparPropertiesComp`、`StressComp` 各跑 `problem.check_partials()`
- **驗收**：所有 partial max abs error < 1e-6

---

### 8. API endpoint tests

- **新建**：`tests/test_api_server.py`
- **內容**：用 FastAPI `TestClient` 覆蓋 `/health`、`/materials`、`/optimize`、`/export`，含失敗路徑（驗 `val_weight == 99999`）

---

## P2｜可觀測性與錯誤處理

### 9. 引入 logging framework

- **問題**：`ansys_export.py` import 了 `logging` 但沒用；其他模組大量 `print()`
- **任務**：
  - 新建 `src/hpa_mdo/core/logging.py`，提供 `get_logger(name)` helper（StreamHandler + 可選 FileHandler）
  - 將 `oas_structural.py`、`optimizer.py`、`vsp_builder.py`、`load_mapper.py` 的 `print()` 改為 `logger.info/debug/warning`
  - **例外**：`scripts/run_optimization.py` 最後一行的 `print(f"val_weight: {value}")` 必須保留（上游 AI agent 的 stdout 協定）

---

### 10. 段長與接頭位置一致性驗證

- **位置**：`src/hpa_mdo/core/config.py`
- **任務**：在 `SparConfig` 加 `@model_validator`：
  - `sum(segments)` 與 `wing.span/2` 在 1e-6 容差內
  - 若 lift wire 啟用，attachment y 必須正好落在累積段邊界（避免 lift wire 位置錯位的 silent bug）
- **驗收**：給出不一致 config 時 `load_config()` 拋 `ValidationError`

---

### 11. 結構化錯誤碼

- **新建**：`src/hpa_mdo/core/errors.py`
- **內容**：定義 `ErrorCode` 枚舉（`CONFIG_INVALID`、`AERO_PARSE_FAIL`、`SOLVER_DIVERGED`、`EXPORT_FAIL`）並讓 API JSON 回應帶上 `error_code` 欄位

---

## P3｜效能優化

### 12. VSPAero 載荷快取

- **位置**：`src/hpa_mdo/aero/vsp_aero.py`
- **問題**：每次呼叫 `optimize_spar()` 都重新 parse `.lod`
- **任務**：加上以 (file path + mtime) 為 key 的 LRU cache；cache size 可從 config 設定（預設 32）
- **驗收**：同一檔案第二次 parse 的執行時間 < 1ms

---

### 13. `DualSparPropertiesComp` 解析導數

- **位置**：`src/hpa_mdo/structure/oas_structural.py`
- **現況**：`method='cs'`（complex-step），約比 analytic 慢 10x
- **任務**：根據平行軸公式手寫 `compute_partials()`；用 Task #7 的 `check_partials` test 驗證
- **預期收益**：optimization wall-clock 改善 30-50%

---

### 14. 兩階段優化 timing profile

- **位置**：`src/hpa_mdo/structure/optimizer.py`
- **任務**：在 `SparOptimizer.optimize()` 用 `time.perf_counter()` 包住 DE 與 SLSQP 階段，輸出到 `OptimizationResult.timing_s` dict，並在 `write_optimization_summary()` 印出

---

## P4｜功能擴展

### 15. 支援可變段數

- **現況**：12 個 DV（6 段 × 2 spar）半寫死
- **任務**：`build_structural_problem()` 改為由 `len(config.spars[i].segments)` 推斷；main / rear 可不同段數
- **驗收**：`segments: [1.5, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0]`（7 段）能正確建出 14 個 DV

---

### 16. 加入薄壁管屈曲約束（Buckling）

- **任務**：
  - 對薄壁管材加入 Euler 柱屈曲與 local shell buckling 約束
  - 新增 `BucklingComp`，輸出 `buckling_index`（= 作用壓力 / 臨界壓力）
  - 納入 KS 聚合，加入 `failure_index_buckling ≤ 0` 約束
- **驗收**：`check_partials` test 通過

---

### 17. 多工況優化

- **現況**：只用單一 trim AoA
- **任務**：config 支援 `flight_cases` 列表：
  ```yaml
  flight_cases:
    - name: cruise
      velocity: 6.5
      load_factor: 1.0
    - name: pull_up
      velocity: 8.0
      load_factor: 2.5
  ```
  每個 case 各有 `failure_index_<case> ≤ 0` 約束，objective 仍為單一 mass
- **驗收**：以 2 個工況跑完 optimization 不報錯，兩個 failure_index 均 ≤ 0

---

### 18. Surrogate model

- `utils/data_collector.py` 已收集 24 欄訓練資料
- **新建**：`src/hpa_mdo/utils/surrogate.py`
- **內容**：用 sklearn GP 或 XGBoost 訓練 `(DV → mass, failure_index)` surrogate，提供 warm start 初始點給 optimizer
- **驗收**：1000 筆資料訓練後，test set failure_index RMSE < 0.05

---

## P5｜DevOps 與文件

### 19. 加入 CI（GitHub Actions）

- **新建**：`.github/workflows/ci.yml`
- **內容**：
  - matrix：`os: [ubuntu-latest, macos-latest, windows-latest]` × `python-version: ["3.10", "3.11", "3.12"]`
  - jobs：`ruff check`、`ruff format --check`、`pytest --cov=hpa_mdo --cov-report=xml`
  - 排除需要 VSPAero 二進位的 integration test（加 `pytest.mark.requires_vspaero`，CI 預設 skip）

---

### 20. pre-commit hooks

- **新建**：`.pre-commit-config.yaml`
- **Hooks**：`ruff`、`ruff-format`、`check-yaml`、`end-of-file-fixer`、`trailing-whitespace`

---

### 21. README 補架構圖

- **位置**：`README.md`
- **任務**：加入 mermaid DAG，畫出 OpenMDAO components 相依關係：
  ```
  SegmentToElement → DualSparProperties → SpatialBeam → StressComp → (KS) → failure_index
  ```
- **新建**：`docs/architecture.md`，含各 component 的 input/output schema 表格

---

### 22. 範例輸出快照

- **新建**：`docs/examples/`
- **放入**：成功跑完的 `optimization_summary.txt`、`beam_analysis.png`，供新使用者比對預期輸出

---

### 23. CLI 工具化

- **位置**：`scripts/run_optimization.py`
- **任務**：改用 `argparse` 或 `typer`，支援：
  - `--config` (path)
  - `--output-dir` (path)
  - `--quiet` (suppress plots)
  - `--no-export` (skip ANSYS export)
- **新增**：`pyproject.toml` 加 `hpa-optimize = hpa_mdo.cli:main` entry point

---

## P6｜Quick Wins

| # | 位置 | 任務 |
|---|------|------|
| 24 | `structure/spar.py` | 確認是否 legacy v1 unused → 若是則刪除，避免混淆 |
| 25 | `src/hpa_mdo/__init__.py` | 把公開 API export 出來，讓 `from hpa_mdo import optimize_spar` 可用 |
| 26 | `pyproject.toml` | 補上 `[tool.pytest.ini_options]` 與 `[tool.coverage.run]` |
| 27 | `pyproject.toml` | 把 `tests/` 與 `examples/` 加入 ruff 檢查範圍 |
| 28 | `core/materials.py` | `MaterialDB` 加 `__contains__` 與 `keys()` 方法 |
| 29 | 根目錄 | `claude.md`（lowercase）與 `CLAUDE.md` 並存 → 確認 source of truth，刪除冗餘 |
| 30 | `pyproject.toml` | `pyproject.toml` 目前有未提交的修改（git status M），確認內容後補 commit |

---

## 建議執行順序

| Sprint | 任務編號 | 風險 | 預期收益 |
|--------|---------|------|---------|
| Sprint 1 修壞東西 | 1, 2, 3, 4 | 低 | 立刻能跑 FSI、消除硬編碼違規 |
| Sprint 2 建立信心 | 5, 6, 7, 8 | 低 | 重構時有安全網 |
| Sprint 3 基礎設施 | 9, 10, 11, 19, 20 | 低 | 可觀測性、CI、驗證 |
| Sprint 4 效能 | 12, 13, 14 | 中 | 優化運算速度 30-50% |
| Sprint 5 擴功能 | 15, 16, 17 | 中-高 | 工程意義最大 |
| Sprint 6 收尾 | 18, 21-30 | 低 | 拋光與文件 |

---

## 重要約束提醒（給 codex）

1. **所有工程參數**必須來自 `configs/*.yaml`，禁止在程式碼中硬編碼物理常數
2. **安全係數**分開：`aerodynamic_load_factor`（載荷）vs `material_safety_factor`（容許應力），禁止合併
3. **結構求解器**必須使用 OpenMDAO，禁止用獨立 scipy beam solver
4. **材料**必須透過 `MaterialDB` 從 `data/materials.yaml` 載入
5. **崩潰時**必須輸出 `val_weight: 99999` 並優雅結束
6. **所有路徑**使用 `pathlib.Path`，不得硬編碼 path separator
7. **高階文件**（README、操作手冊）用繁體中文；log、程式碼註解、`.txt` 報告保持英文
