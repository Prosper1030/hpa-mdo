# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_u_avl_first_outer_loop_rebaseline` | `Wave 14 current` | AVL-first outer-loop rebaseline | `docs/NOW_NEXT_BLUEPRINT.md`, `project_state.yaml`, `docs/TARGET_STANDARD_PROGRAM_PLAN.md`, `docs/task_packs/current_parallel_work/*` | 文件與 task-pack 會明確把 `AVL / lightweight search` 拉回預設 coarse path，並把 `candidate_rerun_vspaero` 降回 shortlist/finalist confirm | 不要改 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml`, 不要順手改 code |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波是方向重定義任務；先不要讓多個 agent 同時重寫 planning / task-pack 文件。
