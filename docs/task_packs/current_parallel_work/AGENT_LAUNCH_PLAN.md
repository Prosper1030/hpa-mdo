# Ground-Clearance Recovery Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是重講整個 repo，而是讓你可以安全地啟動 **Phase 2.9 ground-clearance recovery**，先確認 rerun-aero / solver 已經能跑通之後，怎麼把真正卡住的外翼 jig clearance 拉回來。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 13：先開 1 個 ground-clearance recovery agent**
- **等我驗證這包之後**，再決定是回去重跑 `Track R`，還是直接進 rib ranking sanity review

原因：

- parser/runtime blocker 已經解掉
- explicit wire-truss solver 假性不收斂已經解掉
- 真實 replay 現在不再死在 solver，而是明確卡在 **outer-wing jig ground clearance**
- 這一包應該先修 outer-loop / candidate 產生邏輯，不要和 rib penalty 或 finalist review 混在一起

## 2. 現在就可以丟的 Wave 13

### Agent T：ground-clearance recovery outer-loop

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_t_ground_clearance_recovery_outer_loop.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent T**
2. 等我 review / verify 這包 outer-loop recovery patch
3. 再決定下一步是：
   - 先重跑 `Track R`
   - 如果已經出現非 sentinel 的可比 signal，再決定進 `Track M`
   - 或者如果 ranking 已經看起來合理，直接準備 `Track N`

這樣可以先把真正的設計 blocker 拿掉，不會太早在錯的層上調 rib penalty 或做 finalist 判斷。
