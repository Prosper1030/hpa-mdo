# M-HF3 — CalculiX BUCKLE step（驗證殼式挫曲 KS 聚合）

## 前置條件

M-HF1（Gmsh runner）與 M-HF2（CalculiX 線性靜力 runner）已完成。

## 背景

現有 OpenMDAO 問題中 `buckling_index` 透過薄殼挫曲公式 + KS 聚合算出
（見 `src/hpa_mdo/structure/buckling.py`）。本任務用 CalculiX `*BUCKLE`
step 在高保真驗證層獨立算出前幾個挫曲特徵值 λ，跟 KS 聚合值對照：
若 `λ_1 < 1 / (1 + buckling_index)` 代表 OpenMDAO 的解其實在挫曲 margin
附近，會觸發 WARN。**不改最佳化約束**，只產出報告。

## 目標

1. 在 `hpa_mdo/hifi/calculix_runner.py` 加一個
   `prepare_buckle_inp(mesh_inp_path, out_inp_path, material, boundary,
   reference_load, *, n_modes=5) -> Path`
   - 先下 `*STEP / *STATIC` 做 unit reference load 分析，
   - 再下 `*STEP / *BUCKLE, <n_modes>` 求特徵值。
2. 在 `frd_parser.py` 加
   `parse_buckle_eigenvalues(dat_path) -> list[float]`
   - 讀 CalculiX `.dat`（BUCKLE step 將特徵值寫到 `.dat` 而非 `.frd`）。
   - 回傳 `[λ_1, λ_2, ..., λ_n]`。
3. 新增 script `scripts/hifi_buckle_check.py`：
   - 參數：`--config`、`--mesh`、`--mdo-buckling-index <float>`。
   - 跑 BUCKLE → 取 λ_1 → 計算 `margin = λ_1 - 1.0 / (1.0 - mdo_buckling_index)`。
     （若 mdo_buckling_index 是 failure_index 慣例，margin 的公式請在
     prompt 回應中確認；這裡 Claude 的意圖是：OpenMDAO 報 buckling_index
     為 KS 聚合值，應該介於 [-1, 1]，愈負愈安全；λ_1 愈大愈安全；若兩者
     不一致則印 WARN。）
   - 寫 `output/blackcat_004/hifi/buckle_report.md` 記錄 λ_1..λ_n，
     MDO buckling_index，以及 pass / warn 判定。

## 驗收標準

- Mac mini 上可以實際跑完並產出 buckle_report.md。
- `pytest tests/test_hifi_calculix_runner.py` 有 `prepare_buckle_inp`
  的字串 golden test。
- 主迴圈沒有被影響：`python examples/blackcat_004_optimize.py`
  仍是 `val_weight: 11.95...`（或你跑出來的新值）。

## 不要做的事

- **不要**把 ccx 的 BUCKLE 結果寫進 optimizer 約束 — 只是 post-hoc
  驗證。
- 不要改 `buckling.py` 的公式；若 ccx 結果跟 OpenMDAO 嚴重不一致，
  請在 PR description 裡寫出差異並標記 TODO 給 Claude，不要自己改公式。

## 建議 commit 訊息

```
feat(hifi): M-HF3 CalculiX BUCKLE step + 報告產生器

跟 M-HF2 共用 prepare_*_inp pattern，把 STATIC + BUCKLE 合併到同一個
.inp；在 frd_parser 加 parse_buckle_eigenvalues 讀 .dat。獨立 script
scripts/hifi_buckle_check.py 產出 buckle_report.md，比對 MDO KS
buckling_index 與 ccx λ_1，差異觸發 WARN 不 raise。

Co-Authored-By: Codex 5.4 (Extreme High)
```
