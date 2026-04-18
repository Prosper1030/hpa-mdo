# Rib Campaign Smoke Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是解釋整個 repo，而是讓你可以安全地啟動 **Phase 2.6：rib campaign smoke / sanity review**，先用真 case 檢查目前的 rib candidate contract。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 9：先開 1 個 smoke-review agent**
- **等我驗證這包之後**，再決定是走 tuning 還是 finalist spot-check

原因：

- 目前 rib 模型擴張本身已經 done enough
- 現在最需要的是用真實 campaign 驗證 ranking 是否合理
- 這一包不該再和新的 code 改動混在同一輪，避免把 run evidence 和 patch 混在一起

## 2. 現在就可以丟的 Wave 9

### Agent P：Rib campaign smoke / sanity review

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_p_rib_campaign_smoke_review.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent P**
2. 等我 review / verify Wave 9 smoke report
3. 再決定下一步是：
   - tuning
   - finalist spot-check
   - 或直接維持現狀

這樣可以先用真實 run evidence 判斷 rib integration 到底是不是工程合理，而不是只靠 unit test 自我感覺良好。
