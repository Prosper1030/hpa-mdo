# Rib Integration Agent Launch Plan

> 這份文件是給使用者直接複製貼上用的。  
> 目的不是解釋整個 repo，而是讓你可以安全地啟動 **Phase 2.5：rib integration**，不會一開始就讓多個 agent 在高衝突檔案上撞車。

## 1. 先講結論

現在建議的派工方式是：

- **Wave 6：先開 1 個 foundation agent**
- **Wave 7：等我驗證 Wave 6 之後，再開 2 個可平行 agent**
- **Wave 8：等我驗證 Wave 7 後，再開 zone-wise rib design**

原因：

- 這一波先要把 rib contract 立起來，不能一開始就跳成 optimizer variable
- 其中 `Track M` 和 `Track O` 都可能碰 [scripts/direct_dual_beam_inverse_design.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_inverse_design.py)，所以必須錯開

## 2. 現在就可以丟的 Wave 6

### Agent L：Rib properties foundation

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_l_rib_properties_foundation.md

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 3. 等我驗證後再丟的 Wave 7

### Agent M：Rib bay surrogate contract

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_m_rib_bay_surrogate_contract.md

前提：
- 只有在我確認 Track L 已經 merge / verify 後才開始

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

### Agent N：Passive rib robustness mode

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_n_passive_rib_robustness_mode.md

前提：
- 只有在我確認 Track L 已經 merge / verify 後才開始

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 4. 等我驗證 Wave 7 後再丟的 Wave 8

### Agent O：Zone-wise rib design contract

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_o_zonewise_rib_design_contract.md

前提：
- 只有在我確認 Track M / Track N 都已 merge / verify 後才開始

限制：
- 只能修改 prompt 指定的 write scope
- 不要碰 CURRENT_MAINLINE.md / README.md / docs/GRAND_BLUEPRINT.md / configs/blackcat_004.yaml
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 5. 最簡單的實際操作建議

如果你現在要開始丟 agent，我建議這樣：

1. 先開 **Agent L**
2. 等我 review / verify Wave 6 foundation
3. 再平行開 **Agent M** 和 **Agent N**
4. 等我 review / verify Wave 7
5. 再開 **Agent O**

這樣可以把 rib 工作拆成「先立 contract，再補 robustness，最後再開設計自由度」，避免過早把 still-moving 的主線炸開。
