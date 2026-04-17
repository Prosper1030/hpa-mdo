# Benchmark Basket Tasks

| Task ID | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|
| `benchmark_basket_refresh` | 盤點高保真 / ANSYS / APDL 可比案例 | `docs/task_packs/benchmark_basket/**`, `docs/hi_fidelity_validation_stack.md` | benchmark 候選清單、metadata、建議比較順序 | `scripts/direct_dual_beam_inverse_design.py`, `src/hpa_mdo/hifi/**`, `README.md` |

## Shared Rules

- 先整理 case 與證據，再決定哪些值得升格成當前 benchmark 候選。
- 允許更新 benchmark policy 文件，但不要順手改 solver 或主線腳本。
- 每個結論都應盡量附 case 路徑或 summary 路徑，避免只留下口頭印象。
