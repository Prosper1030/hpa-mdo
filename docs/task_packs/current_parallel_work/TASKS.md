# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_r_multiseed_rib_smoke_signal_hunt` | `Wave 11 current` | Multi-seed rerun-aero rib smoke replay | `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md` | 更新後的 smoke report、至少一組非 sentinel 的 `off` vs `limited_zonewise` 比較、`SANE/SUSPICIOUS/BLOCKED` 判斷 | 不要改 `src/**`, `scripts/**`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波是 run/review 任務；先不要讓多個 agent 同時寫同一份 `rib_campaign_smoke_report.md`。
