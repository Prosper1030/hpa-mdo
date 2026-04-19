# Track M — Rib Signal Sanity Tuning

> 目標：只有在 repaired-shortlist rib smoke 已經有真實可比 signal、但 ranking 仍然 suspicious 時，做最小必要 tuning。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `docs/task_packs/current_parallel_work/reports/avl_postfix_shortlist_refresh_report.md`
7. `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`
8. `scripts/direct_dual_beam_inverse_design.py`
9. `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`

## 前提

這一包只有在：

- post-fix shortlist refresh 已完成
- Track R 已完成
- Track R 結論是 **有真實 rib 訊號，但 ranking 仍 suspicious**

時才應開始。

## 任務目標

做最小必要 tuning，不要擴成新架構。

你優先考慮的只應該是：

- `rib_family_switch_penalty_kg`
- `family_mix_max_unique`
- 必要時很小範圍的 surrogate / summary 權重修正

不要新增新 rib 自由度，不要重新定義 outer-loop。

## 這包最低要做到的事

- 明確指出你根據哪一段 Track R 證據判斷 ranking suspicious
- 只改最小必要參數或 scoring contract
- 補最小必要測試
- 補一份前後對照報告

## 推薦 write scope

- `scripts/direct_dual_beam_inverse_design.py`
- `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- `tests/test_inverse_design.py`
- `docs/task_packs/current_parallel_work/reports/rib_signal_sanity_tuning_report.md`

## 報告最低內容

1. 你為什麼判定需要 tuning
2. 你改了哪些參數或 scoring/summary 邏輯
3. before / after 比較
4. 現在更接近 `SANE` 還是仍然 `SUSPICIOUS`
5. 你認為下一步應該直接進 `Track N` 還是停下來

## 不要做

- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `README.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
- 不要改 `configs/blackcat_004.yaml`
- 不要擴張成新的 rib topology / per-rib optimization
- 不要碰 hi-fi / Track C
