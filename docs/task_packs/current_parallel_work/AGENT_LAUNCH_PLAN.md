# AVL Spanwise Realignment Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是重講整個 repo，而是讓你可以安全地啟動 **Phase 2 outer-loop contract realignment**：
> 先把 `candidate_avl_spanwise` 修回「只補展向載荷 ownership」的版本，再做比較，再回到 repaired AVL-first shortlist。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 15：先開 1 個 Track V agent**
- **等我驗證 Track V 之後**，再開 `Track W`
- **等我驗證 Track W 之後**，再開 `Track X`
- `Track R` 要等 `Track X` 做完才重新啟動

原因：

- Track U 已經證明 AVL spanwise plumbing 可以接通
- 但它同時改掉了 load-state / gate / recovery 節奏，這不是你要的版本
- 所以現在不能直接往後跑 rib smoke 或 tuning
- 正確順序是：**先修 contract drift，再做比較，再重建 shortlist**

## 2. 現在就可以丟的 Wave 15

### Agent V：AVL spanwise ownership realignment

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_v_avl_spanwise_ownership_realign.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 等 Track V 驗完後，再丟 Wave 16 / 17

### Agent W：AVL / legacy / rerun load-state compare

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_w_avl_loadstate_alignment_compare.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

### Agent X：repaired AVL recovered shortlist rebuild

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_x_repaired_avl_recovered_shortlist_rebuild.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 4. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent V**
2. 等我 review / verify Track V
3. 再開 **Agent W**
4. 等我 review / verify Track W
5. 再開 **Agent X**
6. 等我 review / verify Track X
7. 然後才回去重跑 `Track R`

這樣可以先把 `candidate_avl_spanwise` 收回成你真正要的版本，再用 repaired AVL-first path 做後續 rib smoke，不會太早在錯的 load-state 上浪費時間。
