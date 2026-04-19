# Repaired Shortlist Rib Smoke Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是重講整個 repo，而是讓你可以安全地啟動 **Phase 2 repaired-shortlist rib smoke replay**，
> 用 post-fix repaired AVL-first shortlist 重新回答 rib ranking 到底有沒有真實訊號。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 19：先開 1 個 Track R agent**
- **等我驗證 Track R 之後**，視結果二選一：
  - `Track M`：只有 rib ranking 有真實 signal 但仍 suspicious
  - `Track N`：只有 rib ranking 已經 sane，準備做 finalist spot-check / handoff

原因：

- Track Z 已經把 `exp = 1.0` baseline 寫回正確位置
- post-fix repaired AVL-first bounded search 已經自己產生 clean full-gate pass-side shortlist
- 正確順序是：**先用這份新 shortlist 跑 rib 煙霧測試，再根據結果決定 tuning 還是 finalist**

## 2. 現在就可以丟的 Wave 19

### Agent R：repaired-shortlist rib smoke replay

```text
請先閱讀以下文件，先建立上下文，不要自行改主線定義：
/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md
/Volumes/Samsung SSD/hpa-mdo/project_state.yaml
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_PROGRAM_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/RIB_INTEGRATION_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/README.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/reports/avl_postfix_shortlist_refresh_report.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/manifest.yaml

接著只執行這份任務：
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_r_repaired_shortlist_rib_smoke.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 等 Track R 驗完後，再丟後面兩波

### Agent M：rib signal sanity tuning

```text
請先閱讀以下文件，先建立上下文，不要自行改主線定義：
/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md
/Volumes/Samsung SSD/hpa-mdo/project_state.yaml
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_PROGRAM_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/RIB_INTEGRATION_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/README.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/manifest.yaml

接著只執行這份任務：
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_m_rib_signal_sanity_tuning.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

### Agent N：rib finalist spot-check / handoff

```text
請先閱讀以下文件，先建立上下文，不要自行改主線定義：
/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md
/Volumes/Samsung SSD/hpa-mdo/project_state.yaml
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_PROGRAM_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/RIB_INTEGRATION_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/README.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/manifest.yaml

接著只執行這份任務：
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_n_rib_finalist_spotcheck_handoff.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 4. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent R**
2. 等我 review / verify Track R
3. 如果結果是 suspicious 但有真 signal，開 **Agent M**
4. 如果結果已經 sane，直接開 **Agent N**

這樣可以直接用 post-fix repaired AVL-first shortlist 去做 rib smoke，不會再建立在 pre-fix stale seeds 上。
