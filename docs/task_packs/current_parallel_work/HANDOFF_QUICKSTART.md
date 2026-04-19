# Agent Handoff Quickstart

> 這份文件是給使用者直接複製貼上用的。
> 如果你現在要把任務丟給另一個 AI agent，通常只要貼下面其中一段，再指定要做哪個 track。
> 這一波最推薦直接用 [AGENT_LAUNCH_PLAN.md](AGENT_LAUNCH_PLAN.md) 的現成區塊，因為這一波重點不是再發明新流程，而是把 `candidate_avl_spanwise` 收回成「舊 AVL-first 流程 + spanwise lift distribution」。

## 最短版回答

可以。
你現在最簡單的做法，就是直接貼對應模板，然後把任務檔換成 `track_v_avl_spanwise_ownership_realign`、`track_w_avl_loadstate_alignment_compare`、或 `track_x_repaired_avl_recovered_shortlist_rebuild`。

## 通用交辦模板

```text
請先閱讀以下文件，先建立上下文，不要自行改主線定義：
/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md
/Volumes/Samsung SSD/hpa-mdo/project_state.yaml
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/README.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/TASKS.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/manifest.yaml

接著只執行這份任務：
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_v_avl_spanwise_ownership_realign.md

如果本地 repo context 不足，或工具 / solver / library 的行為可能已經變動，可以自行上網查，不要卡在舊文件裡。
上網查時優先看官方文件、solver manual、論文或其他第一手資料，並在回報中簡短說明查了什麼、如何影響你的判斷。

限制：
- 只能修改 task pack 指定的 write scope
- 不要碰 README / CURRENT_MAINLINE / GRAND_BLUEPRINT / configs/blackcat_004.yaml，除非 prompt 明確要求
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 如果你現在就是要派 `Track V`

你可以直接貼下面這段，不需要再自己重寫：

```text
請先閱讀以下文件，先建立上下文，不要自行改主線定義：
/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md
/Volumes/Samsung SSD/hpa-mdo/project_state.yaml
/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/README.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/TASKS.md
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/manifest.yaml

接著只執行這份任務：
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_v_avl_spanwise_ownership_realign.md

你的目標是把目前已經接通的 `candidate_avl_spanwise` 收回成你真正要的版本：保留舊 AVL-first outer-loop 節奏與 gate / recovery 邏輯，只補上 candidate-owned spanwise lift distribution，不要順手改掉 load-state ownership。

如果本地 repo context 不足，或工具 / solver / library 的行為可能已經變動，可以自行上網查，不要卡在舊文件裡。
上網查時優先看官方文件、solver manual、論文或其他第一手資料，並在回報中簡短說明查了什麼、如何影響你的判斷。

限制：
- 只能修改 task pack 指定的 planning / handoff 文件
- 不要改 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml`
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 什麼時候只寫「做 Track T」就夠

只有在對方 agent 已經知道這個 repo，或你確定它會先讀 `CURRENT_MAINLINE.md` / `project_state.yaml` 的情況下，才建議只寫：

```text
請照 current_parallel_work task pack 做 Track T。
```

如果是新 agent，或你不確定它會不會自己找文件，請不要只寫這一句，否則很容易理解不完整。

## 推薦做法

- 新 agent：直接貼完整模板
- 已經在這個 repo 工作過的 agent：可以貼短版，再補 task id
- 一次派多個 agent：這一波先不要；先把 Track V 修正包驗過，再照順序開 Track W / X
- 如果本地資訊不夠，就允許 agent 主動查官方 / 第一手資料，不要把它綁死在 repo 舊文件
