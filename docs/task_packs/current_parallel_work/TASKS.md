# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_t_ground_clearance_recovery_outer_loop` | `Wave 13 current` | Ground-clearance recovery outer-loop | `scripts/direct_dual_beam_inverse_design.py`, `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`, `tests/test_inverse_design.py` | outer-wing jig clearance recovery path、最低限度 replay 證據、可比較的 non-sentinel or improved-clearance candidate 訊號 | 不要改 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml`, 不要在同一包裡調 rib penalty / hi-fi |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波是高衝突核心 outer-loop 任務；先不要讓多個 agent 同時碰 `scripts/direct_dual_beam_inverse_design.py`。
