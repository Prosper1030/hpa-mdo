# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_z_avl_baseline_exponent_rebaseline` | `Wave 18 baseline complete` | 用 repaired AVL-first path 做 `exp=1.0` vs `2.2` apples-to-apples compare，並把 `1.0` 寫回 canonical screening baseline | `docs/task_packs/current_parallel_work/reports/avl_baseline_exponent_rebaseline_report.md` | 明確回答 `2.2` 是否只是 recovery heuristic，並基於 `exp=1.0` 重建 canonical shortlist | 不要順手改 code，不要碰 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_r_repaired_shortlist_rib_smoke` | `Wave 19 current` | 用 post-fix repaired shortlist seeds 重跑 rib smoke，比較 `off` vs `limited_zonewise` | `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md` | 至少一組不是 sentinel fallback 的 repaired-shortlist rib compare，或清楚的新 blocker 判定 | 不要改 `scripts/**`, `src/**`, `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_m_rib_signal_sanity_tuning` | `Wave 20 conditional` | 只有在 repaired-shortlist rib smoke 有真實 signal 但 ranking 可疑時，做最小必要 tuning | `scripts/direct_dual_beam_inverse_design.py`, `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`, `tests/test_inverse_design.py`, `docs/task_packs/current_parallel_work/reports/rib_signal_sanity_tuning_report.md` | 最小必要 penalty / family-cap / summary-weight 調整與對照報告 | 不要碰 `CURRENT_MAINLINE.md`, `README.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml`, 不要擴成新 rib 自由度 |
| `track_n_rib_finalist_spotcheck_handoff` | `Wave 21 conditional` | 只有在 repaired-shortlist rib smoke 結果 sane 時，做 rib finalist spot-check 與 handoff | `docs/task_packs/current_parallel_work/reports/rib_finalist_spotcheck_handoff.md` | finalist 選擇、spot-check 摘要、handoff 建議 | 不要順手改主線 code，不要碰 `CURRENT_MAINLINE.md`, `README.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波的核心規則是：**只補 AVL spanwise lift distribution，不要順手改掉原本 AVL-first 主線的其他 ownership / gate / recovery 假設。**
