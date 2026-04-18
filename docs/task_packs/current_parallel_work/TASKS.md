# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_q_vspaero_lod_parser_fix` | `Wave 10 current` | VSPAero `.lod` parser compatibility fix | `src/hpa_mdo/aero/vsp_aero.py`, `tests/test_vspaero_parser.py`, `tests/test_vspaero_cache.py` | OpenVSP 3.45.3-compatible `.lod` parser、header-name-based column mapping、regression tests | 不要改 `scripts/**`, `src/hpa_mdo/structure/**`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波是高衝突核心任務；先不要讓多個 agent 同時碰 `scripts/direct_dual_beam_inverse_design.py`。
