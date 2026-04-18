# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_l_rib_properties_foundation` | `Wave 6 current` | rib properties foundation | `data/rib_properties.yaml`, `src/hpa_mdo/core/config.py`, `src/hpa_mdo/structure/rib_properties.py`, `tests/test_rib_properties.py`, `tests/test_spar_properties_partials.py` | structured rib family catalog、derived `warping_knockdown` contract、對應測試 | `scripts/direct_dual_beam_inverse_design.py`, `src/hpa_mdo/structure/dual_beam_mainline/**`, `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_m_rib_bay_surrogate_contract` | `Wave 7 after L verification` | rib bay surrogate / shape-retention contract | `src/hpa_mdo/structure/rib_surrogate.py`, `scripts/direct_dual_beam_inverse_design.py`, `tests/test_inverse_design.py` | bay-length / `Δ/c` / shape-retention risk metrics、candidate summary 欄位、對應測試 | Track L 未驗證前不要開始；不要碰 `src/hpa_mdo/structure/dual_beam_mainline/**`, `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md` |
| `track_n_passive_rib_robustness_mode` | `Wave 7 after L verification` | passive rib robustness compare path | `src/hpa_mdo/structure/dual_beam_mainline/types.py`, `src/hpa_mdo/structure/dual_beam_mainline/constraints.py`, `src/hpa_mdo/structure/dual_beam_mainline/rib_link.py`, `tests/test_dual_beam_mainline.py` | passive rib robustness mode、parity vs finite-rib sensitivity compare path、對應測試 | Track L 未驗證前不要開始；不要碰 `scripts/direct_dual_beam_inverse_design.py`, `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md` |
| `track_o_zonewise_rib_design_contract` | `Wave 8 after M/N verification` | zone-wise rib design contract | `scripts/direct_dual_beam_inverse_design.py`, `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`, `tests/test_inverse_design.py` | mandatory-rib-aware zone variables、winner selection consume rib design、對應測試 | Track M / N 未驗證前不要開始；不要碰 `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- 這一波是高衝突核心任務；先不要讓多個 agent 同時碰 `scripts/direct_dual_beam_inverse_design.py`。
