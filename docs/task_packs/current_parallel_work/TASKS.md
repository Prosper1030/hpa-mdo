# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_s_explicit_wire_truss_convergence_unblock` | `Wave 12 current` | Explicit wire-truss convergence unblock | `src/hpa_mdo/structure/dual_beam_mainline/solver.py`, `tests/test_dual_beam_mainline.py`, `tests/test_inverse_design.py` | 可重現/可修復的 wire-truss convergence path、solver regression tests、必要的 inverse-design smoke regression | 不要改 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml`, 不要在同一包裡調 rib penalty |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波是高衝突核心 solver 任務；先不要讓多個 agent 同時碰 `src/hpa_mdo/structure/dual_beam_mainline/solver.py`。
