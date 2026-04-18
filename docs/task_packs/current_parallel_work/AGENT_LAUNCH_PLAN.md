# Rib Smoke Signal-Hunt Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是解釋整個 repo，而是讓你可以安全地啟動 **Phase 2.7 signal hunt**，把 `candidate_rerun_vspaero` 已解卡的路徑轉成真正有訊號的 rib smoke 比較。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 11：先開 1 個 multi-seed smoke agent**
- **等我驗證這包之後**，再決定是進 tuning 還是 finalist spot-check

原因：

- parser/runtime blocker 已經被解掉
- 現在真正缺的是一組不是 sentinel fallback 的 `off` vs `limited_zonewise` 比較
- 這一包應該只跑 smoke / 更新報告，不要和 code patch 或 rib tuning 混在一起

## 2. 現在就可以丟的 Wave 11

### Agent R：multi-seed rib smoke signal hunt

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_r_multiseed_rib_smoke_signal_hunt.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent R**
2. 等我 review / verify Wave 11 smoke report
3. 再決定下一步是：
   - 如果 smoke 還是 `SUSPICIOUS`，進 `Track M`
   - 如果 smoke 已經 `SANE`，進 `Track N`

這樣可以先把真正的 rib ranking 訊號跑出來，不會太早在錯的層上調 penalty 或做 finalist 判斷。
