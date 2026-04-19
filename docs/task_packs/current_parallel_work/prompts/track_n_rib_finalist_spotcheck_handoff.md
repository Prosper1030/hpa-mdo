# Track N — Rib Finalist Spot-Check / Handoff

> 目標：在 repaired-shortlist rib smoke 已經 sane 的前提下，對 rib-on finalist 做最小必要 spot-check 與 handoff。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `docs/task_packs/current_parallel_work/reports/avl_postfix_shortlist_refresh_report.md`
7. `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`
8. `docs/hi_fidelity_validation_stack.md`

## 前提

這一包只有在：

- post-fix shortlist refresh 已完成
- Track R 已完成
- 而且 Track R 的結論已經是 **SANE**

時才應開始。

## 任務目標

先做最小必要的 finalist spot-check 與 handoff，不要把這包包裝成最終 validation truth。

你要回答：

- 哪個 rib-on finalist 最值得往下送？
- 現在有哪些 evidence 已足夠？
- 還有哪些地方只能說是 spot-check / local confidence，而不是 final truth？

## 推薦 write scope

- `docs/task_packs/current_parallel_work/reports/rib_finalist_spotcheck_handoff.md`

## 報告最低內容

1. finalist 候選清單
2. 為什麼這個 rib-on finalist 值得送下去
3. 它相對於 `rib_zonewise=off` 的主要得失
4. 目前 spot-check / compare evidence 摘要
5. 哪些可以說，哪些不能說
6. 後續 handoff 建議：
   - 是否需要 `candidate_rerun_vspaero` confirm
   - 是否需要 local hi-fi spot-check
   - 是否已可進 drawing/handoff 準備

## 不要做

- 不要改主線 code
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `README.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
- 不要改 `configs/blackcat_004.yaml`
- 不要把這包包裝成 final validation truth
