# VSPAero Parser Fix Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是解釋整個 repo，而是讓你可以安全地啟動 **Phase 2.6 blocker resolution**，先修掉 `candidate_rerun_vspaero` 的 parser 相容性問題。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 10：先開 1 個 parser-fix agent**
- **等我驗證這包之後**，再重跑 Track P smoke report

原因：

- 目前 rib 模型擴張本身已經 done enough
- 真實 smoke 已經把 blocker 根因定位到 `VSPAeroParser`
- 這一包應該只修 parser 與測試，不要和 smoke report 或 rib tuning 混在一起

## 2. 現在就可以丟的 Wave 10

### Agent Q：VSPAero `.lod` parser compatibility fix

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_q_vspaero_lod_parser_fix.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent Q**
2. 等我 review / verify Wave 10 parser fix
3. 再決定下一步是：
   - 重跑 Track P smoke
   - 如果 smoke 通過，再進 tuning / finalist spot-check

這樣可以先把已知 blocker 拿掉，不會浪費下一個 agent 再去撞同一個 parser 錯誤。
