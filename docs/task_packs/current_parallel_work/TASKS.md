# Current Parallel Work Tasks

| Task ID | 主題 | 推薦 owner 檔案 | 主要輸出 | 不要碰 |
|---|---|---|---|---|
| `track_b_inverse_design_gate` | inverse-design validity / gate 輸出 | `scripts/direct_dual_beam_inverse_design.py`, `src/hpa_mdo/structure/inverse_design.py`, `tests/test_inverse_design.py` | validity summary artifact、summary JSON 對齊、對應測試 | `README.md`, `CURRENT_MAINLINE.md`, `configs/blackcat_004.yaml` |
| `track_c_mac_hifi_spotcheck` | Mac structural spot-check 收斂 | `src/hpa_mdo/hifi/**`, `scripts/hifi_*`, `tests/test_hifi_*` | benchmark-ready structural check、報告輸出、必要測試 | `scripts/direct_dual_beam_inverse_design.py` |
| `track_d_discrete_layup_summary` | discrete layup 主線化 | `examples/blackcat_004_optimize.py`, `src/hpa_mdo/utils/discrete_layup.py`, `tests/test_discrete_layup*.py` | 更正式的 layup summary / final output | `src/hpa_mdo/hifi/**`, `scripts/direct_dual_beam_inverse_design.py` |

## Shared Rules

- 每個任務都應產出 machine-readable-friendly summary 或清楚可引用的 artifact。
- 每個任務都應附最小驗證，不要只改文件或只改程式碼不驗。
- 每個任務只對自己的 write set 負責，不要順手改別人的檔案。
