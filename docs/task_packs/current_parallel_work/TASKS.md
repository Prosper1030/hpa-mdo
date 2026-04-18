# Current Parallel Work Tasks

| Task ID | Wave | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|---|
| `track_e_recipe_library_foundation` | `Wave 1` | recipe library foundation | `src/hpa_mdo/structure/material_proxy_catalog.py`, `docs/dual_beam_preliminary_material_packages.md`, `tests/test_material_proxy_catalog.py` | 功能型 recipe family、property-row / lookup contract、對應測試 | `src/hpa_mdo/utils/discrete_layup.py`, `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_f_outer_loop_campaign_contract` | `Wave 1` | outer-loop campaign contract | `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`, `scripts/dihedral_sweep_campaign.py`, `tests/test_inverse_design.py` | 更清楚的 candidate score / reject reason、較合理的 quick-analysis search budget、對應測試 | `src/hpa_mdo/structure/material_proxy_catalog.py`, `src/hpa_mdo/utils/discrete_layup.py`, `src/hpa_mdo/hifi/**`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_g_discrete_final_design_wiring` | `Wave 1` | discrete final-design wiring | `examples/blackcat_004_optimize.py`, `src/hpa_mdo/utils/visualization.py`, `tests/test_optimizer_buckling.py`, `tests/test_discrete_layup.py` | 更清楚的 discrete final verdict surfacing、structural recheck summary、對應測試 | `src/hpa_mdo/structure/material_proxy_catalog.py`, `src/hpa_mdo/utils/discrete_layup.py`, `src/hpa_mdo/hifi/**`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml` |
| `track_h_spanwise_dp_search` | `Wave 2 after verification` | spanwise DP discrete search | `src/hpa_mdo/utils/discrete_spanwise_search.py`, `src/hpa_mdo/utils/discrete_layup.py`, `tests/test_discrete_spanwise_search.py`, `tests/test_discrete_layup.py` | DP / shortest-path 類 spanwise discrete selector、transition rule handling、對應測試 | Wave 1 未驗證前不要開始；不要碰 `src/hpa_mdo/structure/material_proxy_catalog.py`, `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md` |
| `track_i_zone_dependent_rules` | `Wave 3 after verification` | zone-dependent floor / ply-drop rules | `src/hpa_mdo/utils/discrete_layup.py`, `docs/dual_beam_preliminary_material_packages.md`, `tests/test_discrete_layup.py` | root / joint / outboard zone rules、對應 gate / 補強假設、對應測試 | Wave 2 未驗證前不要開始；不要碰 `src/hpa_mdo/structure/material_proxy_catalog.py`, `src/hpa_mdo/hifi/**`, `CURRENT_MAINLINE.md` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
- 如果本地 repo context 不足，或工具 / solver / library 的事實可能已變動，可以自行上網查；優先用官方文件、manual、論文或其他第一手資料。
- 如果有上網查，回報時要簡短交代查了什麼，以及它如何影響判斷或實作。
- Wave 2 / Wave 3 任務必須等前一波經過整合與驗證後再啟動，不要提早開工。
