# Explicit Wire-Truss Convergence Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是解釋整個 repo，而是讓你可以安全地啟動 **Phase 2.8 solver unblock**，先把 explicit wire-truss Newton / line-search 收斂問題解掉。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 12：先開 1 個 wire-truss convergence agent**
- **等我驗證這包之後**，再決定是進 tuning 還是 finalist spot-check

原因：

- parser/runtime blocker 已經被解掉
- Track R 多 seed smoke 已經把 immediate blocker 壓縮到 explicit wire-truss 收斂
- 這一包應該只修 solver / 測試，不要和 rib tuning 或 finalist review 混在一起

## 2. 現在就可以丟的 Wave 12

### Agent S：explicit wire-truss convergence unblock

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_s_explicit_wire_truss_convergence_unblock.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent S**
2. 等我 review / verify Wave 12 solver patch
3. 再決定下一步是：
   - 先重跑 `Track R`
   - 再依結果決定進 `Track M` 或 `Track N`

這樣可以先把真正的 inner solver blocker 拿掉，不會太早在錯的層上調 penalty 或做 finalist 判斷。
