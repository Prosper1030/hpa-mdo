# HPA-MDO 專案 Review 與優化清單

> 產出日期：2026-04-07｜最後更新：2026-04-08（buckling silent failure 補強完成）
> 基於完整原始碼靜態分析

## 整體評價

架構乾淨、config 管理嚴謹、安全係數分離正確、跨平台 path 處理良好。
**目前 49 個測試全部通過，P0–P3、P5–P6、P4#15–16 已完成。**
所有 Finding 1/2/3 物理 bug 已修正，屈曲約束已上線並強制執行於所有優化路徑。

**Active constraint 分析（端到端驗證 14.3579 kg）**：
- `tip_deflection` : 96.4% budget（**唯一綁定約束**）
- `failure_index`  : 32.1% budget（78% margin）
- `twist_max`      : 16.4% budget
- `buckling_index` : 14.4% budget（被動滿足，-0.856）
- 結論：Black Cat 004 為「剛度受限」設計，不是強度或屈曲受限

---

## 進度總覽

| Sprint | 狀態 | 完成項目 |
|--------|------|---------|
| P0 必修缺陷 | ✅ 完成 | FSI修復、移除硬編碼、輸入驗證、動態段數 |
| P1 測試補強 | ✅ 完成 | 46 tests passing |
| P2 可觀測性 | ✅ 完成 | logging、errors.py、API error_code |
| P3 效能優化 | ✅ 部分 | VSPAero cache、計時器（解析導數待做） |
| P4 功能擴展 | 🔄 進行中 | 可變段數 ✅、殼體屈曲 ✅、多工況 ⬜、surrogate ⬜ |
| P5 DevOps | ✅ 完成 | CI、pre-commit、CLI argparse |
| P6 Quick wins | ✅ 完成 | MaterialDB、__init__、spar.py、README |
| **Physics fixes** | ✅ 完成 | Finding 1 (KS twist)、Finding 2 (lumped mass)、Finding 3 (clip bug) |

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

### 16. 薄壁管屈曲約束 ✅
- `structure/buckling.py` → `BucklingComp` ✅
- **只使用 shell local buckling**（Timoshenko-Gere）
  - 經典係數 0.605
  - NASA SP-8007 knockdown γ = 0.65
  - Bending enhancement β = 1.3
  - 合併係數 coef = 0.605 × 0.65 × 1.3 ≈ 0.511
- Euler 柱屈曲對 HPA 不適用（order-of-magnitude 分析顯示安全邊際 > 100×），故省略
- 雙翼梁共用 `kappa_flap`（同垂直高度假設）
- KS 聚合（ρ=50, max-shift 穩定版）→ `buckling_index ≤ 0`
- check_partials（cs method）驗證通過 ✅
- 質量影響：12.77 → 14.36 kg（+12.4%），壁厚從 0.8mm 上限被推離，符合工程預期

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

## Physics Fixes（2026-04-08 完成）

### Finding 1：TwistConstraintComp 只看翼尖 ✅
- **Bug**：`theta_tip = theta_twist[-1]` 假設翼尖永遠是最大 twist，對有 pitching moment 反轉的機翼會漏抓中段尖峰
- **Fix**：改用全節點 KS 聚合（ρ=100，無因次化避免 `log(n)/ρ` 節點數偏置）
- 測試：`test_twist_constraint.py` 驗證中段 0.03 rad > 翼尖 0.01 rad 時能抓到中段
- Commits: `243f70f`, `689b873`

### Finding 2：ExternalLoadsComp 自重量綱錯誤 ✅
- **Bug**：舊寫法 `weight_per_span[e] += mpl[e] * g / 2.0` 單位是 N/m 而不是 N，沒乘 element length
- **Fix**：改為 element-based lumped mass：`element_weight = mpl[e] * g * L_e`，兩端各分 1/2
- Commit: `78d3ab4`

### Finding 3：LoadMapper clip bug（total_lift 膨脹）✅
- **Bug**：`np.clip(y_s, y_a.min(), y_a.max())` 會讓超出 aero 範圍的結構節點 **重複採樣** 端點，導致 `total_lift` 超過真實積分值
- **Fix**：加 `in_range_mask`，超出範圍的節點載荷設為 0；chord/cl/cm 保留 clamp 值（幾何參數）
- 測試：`test_clip_bug_total_lift_matches_integration` 驗證舊行為 250N vs 正確 150N
- Commits: `9ca6e33`, `bb47f2a`, `59c6b14`（docstring polish）

### Buckling Silent Failure：scipy 路徑強制執行屈曲約束 ✅
- **Bug**：`BucklingComp` 在 OpenMDAO 已透過 `add_constraint` 註冊，但 scipy DE/SLSQP 路徑把 OpenMDAO 當 black-box，`_eval()` 字典只含 mass/failure/twist/tip_defl，**沒有 buckling**。導致 scipy 路徑完全忽略屈曲約束（silent failure mode）
- 端到端驗證後發現：目前運氣好，因為 `tip_deflection` 主導把牆推厚到 buckling 被動滿足（-0.856），但 config 改動可能無預警產生違反屈曲的「最佳解」
- **Fix**：
  - `_eval` 字典加入 `buckling`
  - `penalty_obj` 加入 800 × (1 + buckling)² 懲罰
  - SLSQP `constraints` 加入 buckling 不等式
  - `de_feas / sq_feas / 最終 success` 三處可行性檢查都加入 buckling
  - infeasible fallback 的 violation sum 加入 buckling
  - `_optimize_openmdao` 與 `auto` 模式也加入 buckling 檢查
  - `OptimizationResult` 加入 `buckling_index` 必填欄位（連動 server.py / mcp_server.py / test fixtures）
  - `visualization.py` 兩處 feasibility + summary 報告加入 `Buckling index` 行
  - `_extract_results` 加入 `buckling_index` key
- 驗證：`val_weight: 14.3579 kg`（與 baseline 完全相同，證明懲罰沒扭曲 DE 搜尋）
- 測試：`test_optimizer_buckling.py` 三個測試（dataclass 欄位、_eval 字典、summary 文字）
- Commits: `e6acd35`（程式邏輯）、`35b0517`（測試）

---

## 已知小問題（待修）

| 位置 | 問題 | 優先度 |
|------|------|--------|
| `optimizer.py:275-276` | `ndim>0 array→scalar` DeprecationWarning | ✅ 已修（`0ec4576`） |
| `np.trapz` deprecation | 全面改用 `np.trapezoid` | ✅ 已修（`bfdb0c3`） |
| `BucklingComp` ks_rho=50 與 Twist 不一致 | 統一從 `config.safety` 讀取 | ✅ 已修（`a307361`） |
| **scipy 路徑沒檢查 buckling**（latent silent failure） | 補強 `_eval` / penalty / SLSQP / feasibility | ✅ 已修（`e6acd35`、`35b0517`） |
| `oas_structural.py:425` | `Iz_e = Iy[e]` 對稱管近似（Finding 4），HPA 可接受 | 低（保留） |
| `oas_structural.py:440` | DE 邊界 `K_elem_global = T.T @ K_local @ T` divide-by-zero RuntimeWarning | 低（DE 探索退化設計，不影響收斂） |
| `test_api_server.py` slow tests | 在 Mac Mini 環境耗時 5+ 分鐘 | 低（用 `-m 'not slow'` 規避） |

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
