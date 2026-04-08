# HPA-MDO 專案 Review 與優化清單

> 產出日期：2026-04-07｜最後更新：2026-04-08
> 基於完整原始碼靜態分析

## 整體評價

架構乾淨、config 管理嚴謹、安全係數分離正確、跨平台 path 處理良好。
**目前 40 個測試全部通過，P0–P3、P5–P6 已完成，剩餘 P4 功能擴展。**

---

## 進度總覽

| Sprint | 狀態 | 完成項目 |
|--------|------|---------|
| P0 必修缺陷 | ✅ 完成 | FSI修復、移除硬編碼、輸入驗證、動態段數 |
| P1 測試補強 | ✅ 完成 | 40 tests passing |
| P2 可觀測性 | ✅ 完成 | logging、errors.py、API error_code |
| P3 效能優化 | ✅ 部分 | VSPAero cache、計時器（解析導數待做） |
| P4 功能擴展 | 🔄 進行中 | 可變段數完成，其餘待做 |
| P5 DevOps | ✅ 完成 | CI、pre-commit、CLI argparse |
| P6 Quick wins | ✅ 完成 | MaterialDB、__init__、spar.py、README |

---

## P0｜必修缺陷 ✅

### 1. `fsi/coupling.py` ✅
### 2. 硬編碼 tc 值搬到 config ✅
### 3. `_N_SEG=6` 改動態 ✅
### 4. `LoadMapper` 輸入驗證 ✅

---

## P1｜測試補強 ✅

### 5. Unit tests ✅
- `test_vspaero_parser.py` ✅
- `test_xflr5_parser.py` ✅
- `test_materials_db.py` ✅
- `test_load_mapper.py` ✅（9 tests）
- `test_data_collector.py` ✅

### 6. Integration test ✅
- `test_blackcat_pipeline.py` ✅（@pytest.mark.slow）

### 7. OpenMDAO check_partials ⬜ 待做
- `tests/test_partials.py`

### 8. API endpoint tests ✅
- `test_api_server.py` ✅（5 tests）

---

## P2｜可觀測性與錯誤處理 ✅

### 9. Logging framework ✅
- `core/logging.py` ✅
- oas_structural、optimizer、vsp_builder、load_mapper 改用 logger ✅

### 10. 段長與接頭位置驗證 ✅
- `config.py` model_validator ✅

### 11. 結構化錯誤碼 ✅
- `core/errors.py` ✅（HPAError、ErrorCode）
- API 回應加入 `error_code` 欄位 ✅

---

## P3｜效能優化

### 12. VSPAero 載荷快取 ✅
- mtime-based LRU cache，第二次 parse < 1ms ✅
- `test_vspaero_cache.py` ✅

### 13. `DualSparPropertiesComp` 解析導數 ⬜ 待做
- **高優先**：目前用 complex-step，比 analytic 慢 10x
- 需手寫平行軸定理的 compute_partials()
- 完成後跑 check_partials 驗證

### 14. 兩階段計時 ✅
- `OptimizationResult.timing_s` dict ✅
- summary 報告加入計時區塊 ✅

---

## P4｜功能擴展 🔄

### 15. 可變段數 ✅
- build_structural_problem() 動態讀 len(segments) ✅

### 16. 薄壁管屈曲約束 ⬜ 待做
- 新增 `BucklingComp`（Euler柱屈曲 + local shell buckling）
- KS 聚合 → `failure_index_buckling ≤ 0`
- check_partials 驗證

### 17. 多工況優化 ⬜ 待做
- config 支援 `flight_cases` 列表
- 每個 case 各有 `failure_index_<case> ≤ 0` 約束
- objective 仍為單一 mass

### 18. Surrogate model ⬜ 待做
- `utils/surrogate.py`
- sklearn GP 或 XGBoost
- warm start 初始點

---

## P5｜DevOps 與文件 ✅

### 19. GitHub Actions CI ✅
### 20. pre-commit hooks ✅
### 21. README mermaid 架構圖 ✅
### 22. 範例輸出快照 ⬜ 待做
- `docs/examples/` 放 optimization_summary.txt、beam_analysis.png
### 23. CLI 工具化 ✅
- argparse（--config、--output-dir、--quiet、--no-export、--aoa）✅
- `hpa-optimize` entry point ✅

---

## P6｜Quick Wins ✅

| # | 任務 | 狀態 |
|---|------|------|
| 24 | spar.py 標記 deprecated | ✅ |
| 25 | __init__.py 公開 API | ✅ |
| 26 | pyproject.toml 補齊 | ✅ |
| 27 | tests/ 加入 ruff 範圍 | ✅（CI 涵蓋） |
| 28 | MaterialDB __contains__ + keys() | ✅ |
| 29 | claude.md 重複確認 | ✅（CLAUDE.md 為主） |
| 30 | uv.lock 加入 .gitignore | ✅ |

---

## 已知小問題（待修）

| 位置 | 問題 | 優先度 |
|------|------|--------|
| `optimizer.py:275-276` | `ndim>0 array→scalar` DeprecationWarning | 低 |
| `np.trapz` in tests | 部分仍有 deprecation warning | 低 |

---

## 重要約束提醒（給 codex）

1. **所有工程參數**必須來自 `configs/*.yaml`，禁止硬編碼物理常數
2. **安全係數**分開：`aerodynamic_load_factor`（載荷）vs `material_safety_factor`（容許應力）
3. **結構求解器**必須使用 OpenMDAO，禁止獨立 scipy beam solver
4. **材料**必須透過 `MaterialDB` 從 `data/materials.yaml` 載入
5. **崩潰時**必須輸出 `val_weight: 99999` 並優雅結束
6. **所有路徑**使用 `pathlib.Path`
7. **高階文件**用繁體中文；log、程式碼註解、`.txt` 報告保持英文
8. **每個任務完成後**：git commit → git pull --rebase --autostash origin main → git push origin main
