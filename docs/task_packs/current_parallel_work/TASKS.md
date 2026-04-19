# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_v_avl_spanwise_ownership_realign` | `Wave 15 current` | 把 `candidate_avl_spanwise` 修回「只補展向載荷 ownership」 | `scripts/dihedral_sweep_campaign.py`, `scripts/direct_dual_beam_inverse_design.py`, `src/hpa_mdo/aero/avl_spanwise.py`, `tests/test_avl_spanwise.py`, `tests/test_inverse_design.py` | repaired AVL spanwise path，不再順手改掉 load-state / gate / recovery 邏輯 | 不要改 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml`，不要碰 hi-fi / rib penalty |
| `track_w_avl_loadstate_alignment_compare` | `Wave 16 after V verify` | 比較 repaired AVL、legacy、rerun 三條路徑的 load-state 是否真的對齊 | `docs/task_packs/current_parallel_work/reports/avl_loadstate_alignment_report.md` | 對照 report，明確回答 repaired AVL path 是不是「舊流程 + spanwise lift distribution」 | 不要順手改 code；除非對比過程暴露出新的明確 blocker 並先停下來回報 |
| `track_x_repaired_avl_recovered_shortlist_rebuild` | `Wave 17 after W verify` | 用 repaired AVL-first path 重建 pass-side recovered shortlist，供後續 Track R 使用 | `docs/task_packs/current_parallel_work/reports/repaired_avl_shortlist_report.md` | `2 到 4` 個 repaired shortlist seeds 與交接建議，明確說明哪些值得送去 rerun confirm / rib smoke | 不要順手進 Track R / M / N，不要改 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波的核心規則是：**只補 AVL spanwise lift distribution，不要順手改掉原本 AVL-first 主線的其他 ownership / gate / recovery 假設。**
