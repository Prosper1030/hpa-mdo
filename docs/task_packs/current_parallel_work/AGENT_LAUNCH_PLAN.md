# Rerun-Aero Outer-Loop Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是解釋整個 repo，而是讓你可以安全地啟動 **Wave 4：rerun-aero outer loop**，不會一開始就讓多個 agent 在核心求解腳本上撞車。

## 1. 先講結論

現在建議的派工方式不是一次開很多個 thread，而是：

- **Wave 4：先開 1 個核心 agent**
- **Wave 5：等我驗證 Wave 4 之後，再開 consumer / campaign 對接**

原因：

- 這一波的核心任務會碰 [scripts/direct_dual_beam_inverse_design.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_inverse_design.py)
- 這是高衝突主幹檔，不適合一開始就多 agent 併改

## 2. 現在就可以丟的 Wave 4

### Agent F：Rerun-aero outer-loop core

```text
請先閱讀以下文件，先建立上下文，不要自行改主線定義：
/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md
/Volumes/Samsung SSD/hpa-mdo/project_state.yaml
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_PROGRAM_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/README.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/manifest.yaml

接著只執行這份任務：
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_j_rerun_aero_outer_loop_core.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 等我驗證後再丟的 Wave 5

### Agent G：Campaign consumer for rerun-aero artifacts

```text
請先閱讀以下文件，先建立上下文，不要自行改主線定義：
/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md
/Volumes/Samsung SSD/hpa-mdo/project_state.yaml
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_PROGRAM_PLAN.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/README.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/manifest.yaml

接著只執行這份任務：
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_k_rerun_aero_campaign_consumer.md

前提：
- 只有在我確認 rerun-aero outer-loop core 已經 merge / verify 後才開始

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 4. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent F**
2. 等我 review / verify Wave 4 core
3. 再開 **Agent G**

這樣雖然比多 agent 並發慢一點，但能避免核心 solver / outer-loop contract 在高衝突檔上互撞。
