# OpenMDAO Driver vs SciPy 黑盒路徑 Benchmark

## 動機

P3#13 已經把 `DualSparPropertiesComp` 換成解析偏導；這次量測的目的，是確認這些偏導在 `method="openmdao"` 與 `method="scipy"` 兩條最佳化路徑裡，實際上有沒有被用到，以及兩條路徑目前能不能收斂到可比較的結果。

## 量測方法

- 使用同一份 `configs/blackcat_004.yaml`，並沿用 `blackcat_004` example 的流程：
  選取最接近機重的 AoA case，再套用 `aerodynamic_load_factor`。
- 每個方法都用 fresh `SparOptimizer` cold start 一次，避免沿用前一次 `Problem` 狀態。
- 在 `DualSparPropertiesComp` 上加入 class-level counter：
  - `n_compute`
  - `n_compute_partials`
- 由於實際 class 定義在 [oas_structural.py](/Volumes/Samsung%20SSD/hpa-mdo/src/hpa_mdo/structure/oas_structural.py)，counter 是加在這裡，而不是 prompt 文字裡提到的 `spar_model.py`。
- benchmark 腳本不畫圖，只輸出 JSON 與終端摘要：
  [benchmark_openmdao_vs_scipy.py](/Volumes/Samsung%20SSD/hpa-mdo/examples/benchmark_openmdao_vs_scipy.py)

## 結果表

| 項目 | `openmdao` | `scipy` |
| --- | ---: | ---: |
| success | `True` | `True` |
| message / error | `OpenMDAO converged` | `scipy converged (feasible)` |
| total_mass_full_kg | `10.898230` | `10.898327` |
| failure_index | `-0.734876` | `-0.735083` |
| buckling_index | `-0.815377` | `-0.815289` |
| twist_max_deg | `0.421276` | `0.421249` |
| tip_deflection_m | `2.500000` | `2.499964` |
| wall_time_s | `64.854672` | `111.526602` |
| timing_s | `{}` | `{"de_global_s": 109.476023, "slsqp_local_s": 2.019619, "total_s": 111.526472}` |
| n_compute | `19` | `388` |
| n_compute_partials | `18` | `0` |

原始結果檔：
[openmdao_vs_scipy_benchmark.json](/Volumes/Samsung%20SSD/hpa-mdo/docs/openmdao_vs_scipy_benchmark.json)

## 解讀

- `openmdao` 路徑的 `n_compute_partials = 18`，表示 P3#13 的解析偏導**確實有被 OpenMDAO driver 持續使用**，而不只是擦邊碰到一次。
- `scipy` 路徑的 `n_compute_partials = 0`，也符合先前結論：黑盒路徑本來就不會用到 `DualSparPropertiesComp.compute_partials()`。
- `scipy` 路徑在 `workers=-1` 下已可正常執行，表示先前 multiprocessing 對 local closure 的 pickling 問題已解除。
- 這次 benchmark 下，兩條路徑**已經收斂到幾乎等價的解**：
  - `openmdao`：`10.898230 kg`
  - `scipy`：`10.898327 kg`
  - 兩者差約 `9.74e-05 kg`
- 修復後，先前那條 `struct.mass.total_mass_full` 不受 DV 影響的 OpenMDAO warning 沒再出現；搭配 `compute_totals` 驗證也可看到 objective 對各 DV 的梯度 norm 都已非零。
- 相對地，`scipy` 黑盒路徑做了 `388` 次 `compute()`、`0` 次 `compute_partials()`；`openmdao` 路徑則以 `19` 次 `compute()`、`18` 次 `compute_partials()` 收斂到幾乎相同的解，而且 wall time 更短。

## 下一步建議

- 下一步比較值得做的是再把剩餘的 FEM runtime warning（`matmul` overflow / invalid）縮到最小，確認它們不會影響大範圍設計點的穩定性。
- 從這次數據來看：
  - 解析偏導已被 `openmdao` 路徑有效利用；
  - `scipy` 路徑仍不會用到它，但 `workers=-1` 已可穩定運行；
  - 在 blackcat_004 這個案例上，`openmdao` 已經具備成為預設路徑的數據基礎，只是切換 default 前，仍建議再用一兩個不同工況或 config 交叉驗證一次。
