# F13 — Tsai-Wu / Tsai-Hill 複合材料破壞準則約束

## 前置條件

目前 `failure_index` 只比對 von Mises 對等向材料（鋁）有效，對 CFRP
tube 並不正確 — CFRP 的軸向 / 橫向 / 剪切強度差 1-2 個數量級，von Mises
會嚴重低估或誤判。

## 背景

我們的翼梁材料是 `carbon_fiber_hm` 單向 CFRP tube，正交異向性。正確的
破壞準則是 **Tsai-Wu**（二次互動）或簡化的 **Tsai-Hill**。`materials.yaml`
裡 `carbon_fiber_hm` 已經有 `sigma_tension_longitudinal`、
`sigma_compression_longitudinal`、`sigma_tension_transverse`、
`sigma_compression_transverse`、`tau_shear` 這些參數（如果沒有請補齊）。

## 目標

1. 在 `src/hpa_mdo/structure/failure_criteria.py`（新檔）實作：
   - `tsai_wu_index(sigma_11, sigma_22, tau_12, material) -> float`
     - 公式：
       ```
       F11*σ₁² + F22*σ₂² + F66*τ₁₂² + 2*F12*σ₁*σ₂ + F1*σ₁ + F2*σ₂ ≤ 1
       ```
       F1 = 1/Xt - 1/Xc，F2 = 1/Yt - 1/Yc，F11 = 1/(Xt*Xc)，etc。
       F12 用簡化形式 `F12 = -0.5 * sqrt(F11*F22)`。
     - 回傳值 `Tsai-Wu index`，≤ 1 代表安全。
   - `tsai_hill_index(...)` 同形式，簡化版。
2. 在 `hpa_mdo.structure.oas_structural` 增加 `FailureIndexComp`
   OpenMDAO ExplicitComponent：
   - Inputs：各段元素的 `sigma_axial`、`sigma_hoop`（目前只有 σ₁，σ₂ ≈ 0
     對於薄壁管，但保留介面）、`tau_torsion`。
   - Output：每段的 Tsai-Wu index。
   - Outputs 透過 KS aggregation 變成單一 `failure_index`（保持現有的
     `failure_index ≤ 0` 約束介面；`index = tsai_wu - 1.0`）。
3. `configs/blackcat_004.yaml` 增 `structure.failure_criterion: "tsai_wu"`
   旗標；預設值應該跑出跟 von Mises 差不多的 `val_weight`（管壁受軸向為主，
   σ₂ / τ₁₂ 很小），但兩種都要能切換。

## 驗收標準

- `python examples/blackcat_004_optimize.py`：
  - `failure_criterion: von_mises` → `val_weight: 11.95...`（baseline）。
  - `failure_criterion: tsai_wu` → `val_weight` 變動在 ±3% 之內，
    PR description 記錄實際數字。
- `pytest tests/test_failure_criteria.py`：單點測試（給已知 σ / material
  → 手算 Tsai-Wu value，float 比對）。
- `check_partials` 對新的 `FailureIndexComp` 通過（相對誤差 < 1e-4）。

## 不要做的事

- 不要把 σ₂（環向應力）假設為零就 skip — 保留 input 與 deriv 路徑；
  目前值很小但未來加內壓 / 彎扭耦合時會用到。
- 不要刪舊的 von Mises 路徑；它是等向性材料（Al 7075 等）必要的。
- 不要自己調 material 參數硬做 Tsai-Wu pass；如果跑出來 infeasible，
  在 PR description 裡標 TODO 給 Claude 看，不要靜默改 materials.yaml。

## 建議 commit 訊息

```
feat(structure): F13 Tsai-Wu / Tsai-Hill 複合材料破壞準則

新增 hpa_mdo.structure.failure_criteria 與 FailureIndexComp，接到
OpenMDAO problem 的 KS 聚合路徑；configs 加 failure_criterion 旗標，
預設仍為 von_mises 保持 backward compatible。CFRP 設計切到 tsai_wu
時 val_weight 差 < 3%。

Co-Authored-By: Codex 5.4 (Extreme High)
```
