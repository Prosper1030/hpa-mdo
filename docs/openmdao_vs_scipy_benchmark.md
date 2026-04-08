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
| success | `True` | `False` |
| message / error | `OpenMDAO converged` | `AttributeError: Can't pickle local object 'SparOptimizer._optimize_scipy.<locals>.penalty_obj'` |
| total_mass_full_kg | `45.150570` | `N/A` |
| failure_index | `-0.935091` | `N/A` |
| buckling_index | `-0.900964` | `N/A` |
| twist_max_deg | `0.041156` | `N/A` |
| tip_deflection_m | `0.205726` | `N/A` |
| wall_time_s | `4.040410` | `0.294553` |
| timing_s | `{}` | `{}` |
| n_compute | `2` | `0` |
| n_compute_partials | `1` | `0` |

原始結果檔：
[openmdao_vs_scipy_benchmark.json](/Volumes/Samsung%20SSD/hpa-mdo/docs/openmdao_vs_scipy_benchmark.json)

`scipy` 路徑 traceback 摘要如下：

```text
AttributeError: Can't pickle local object 'SparOptimizer._optimize_scipy.<locals>.penalty_obj'
```

這個錯誤發生在 `differential_evolution(..., workers=-1)` 啟用 multiprocessing 後，SciPy 需要 pickle `penalty_obj`，但 `_optimize_scipy()` 目前把它定義成 local closure。

## 解讀

- `openmdao` 路徑的 `n_compute_partials = 1`，表示 P3#13 的解析偏導**確實有被 OpenMDAO driver 走到**。這是目前最直接的證據。
- `scipy` 路徑的 `n_compute_partials = 0`，也符合先前結論：黑盒路徑本來就不會用到 `DualSparPropertiesComp.compute_partials()`。
- 但這次 benchmark 下，兩條路徑**還不能視為收斂到等價解**：
  - `openmdao` 得到 `45.150570 kg`
  - `scipy` 因 `workers=-1` 的 pickle 問題，在 DE 開始時就中止，沒有最終設計點可比
- `openmdao` 雖然成功結束，卻同時出現 OpenMDAO 的 derivative warning：

```text
The following constraints or objectives cannot be impacted by the design variables
at the current design point: struct.mass.total_mass_full
```

這和它只做 `1` 次 function evaluation / `1` 次 gradient evaluation、最後停在明顯偏重的 `45.15 kg` 解，是一致的訊號：目前 OpenMDAO driver 路徑雖然有進到偏導計算，但總導數/可影響性判定仍有問題，尚不足以和原本 `scipy` 黑盒路徑做有效 apples-to-apples 比較。

## 下一步建議

- 先分開處理兩個問題，再決定是否調整 example default：
  1. `scipy` 路徑：釐清 `workers=-1` 下 local closure 的 pickling 問題，讓 benchmark 能重新拿到黑盒基準解。
  2. `openmdao` 路徑：排查 `struct.mass.total_mass_full` 被判定為不受 DV 影響的原因，確認 driver 真正看到正確的 total derivatives。
- 在這兩個問題修正前，現有數據只足以支持：
  - 解析偏導已被 `openmdao` 路徑觸發；
  - `scipy` 路徑仍不會用到它；
  - 但目前還**不足以**支持把 `examples/blackcat_004_optimize.py` 的 default 直接切到 `method="openmdao"`。
