# Current Parallel Work Tasks

| Task ID | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|
| `track_a_frontdoor_workflow` | 主線 front door / canonical workflow 收斂 | `docs/README.md`, `docs/dual_beam_workflow_architecture_overview.md`, `docs/task_packs/current_parallel_work/**` | 更清楚的 front-door workflow、artifact 導航、handoff-ready docs | `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_e_surrogate_warm_start` | surrogate warm start / data / catalog | `src/hpa_mdo/utils/surrogate.py`, `src/hpa_mdo/utils/data_collector.py`, `src/hpa_mdo/structure/optimizer.py`, `scripts/collect_surrogate_data.py`, `tests/test_surrogate.py`, `pyproject.toml` | optional surrogate backend、warm-start wiring、資料收集腳本、測試 | `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, 未經明確需求不要改 solver 核心 physics 假設 |
| `track_f_requested_realizable_outer_loop` | requested-to-realizable 低維外圈 | `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`, `scripts/dihedral_sweep_campaign.py`, `docs/task_packs/current_parallel_work/**`, `tests/test_inverse_design.py` | 低維 outer-loop score / summary、requested-vs-realizable mismatch evidence、對應測試 | `src/hpa_mdo/hifi/**`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
