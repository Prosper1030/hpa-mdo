# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_j_rerun_aero_outer_loop_core` | `Wave 4 current` | rerun-aero outer-loop core | `scripts/direct_dual_beam_inverse_design.py`, `src/hpa_mdo/aero/vsp_builder.py`, `src/hpa_mdo/aero/vsp_aero.py`, `src/hpa_mdo/aero/load_mapper.py`, `tests/test_inverse_design.py` | candidate-level geometry rebuild、rerun-aero contract、load ownership / summary evidence、對應測試 | `src/hpa_mdo/hifi/**`, `src/hpa_mdo/utils/discrete_layup.py`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_k_rerun_aero_campaign_consumer` | `Wave 5 after verification` | campaign consumer for rerun-aero artifacts | `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`, `scripts/dihedral_sweep_campaign.py`, `tests/test_inverse_design.py` | campaign / winner selection consume 新的 rerun-aero artifacts、reject reason / winner evidence 更新、對應測試 | Wave 4 未驗證前不要開始；不要碰 `scripts/direct_dual_beam_inverse_design.py`, `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波是高衝突核心任務；先不要讓多個 agent 同時碰 `scripts/direct_dual_beam_inverse_design.py`。
