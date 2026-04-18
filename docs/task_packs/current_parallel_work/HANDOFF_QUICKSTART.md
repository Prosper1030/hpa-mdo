# Agent Handoff Quickstart

> 這份文件是給使用者直接複製貼上用的。
> 如果你現在要把任務丟給另一個 AI agent，通常只要貼下面其中一段，再指定要做哪個 track。
> 這一波最推薦直接用 [AGENT_LAUNCH_PLAN.md](AGENT_LAUNCH_PLAN.md) 的現成區塊，因為這一波重點是 explicit wire-truss 收斂，不是再擴模型。

## 最短版回答

可以。
你現在最簡單的做法，就是直接貼對應模板，然後把任務檔換成 `track_s_explicit_wire_truss_convergence_unblock`。

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_s_explicit_wire_truss_convergence_unblock.md

如果本地 repo context 不足，或工具 / solver / library 的行為可能已經變動，可以自行上網查，不要卡在舊文件裡。
上網查時優先看官方文件、solver manual、論文或其他第一手資料，並在回報中簡短說明查了什麼、如何影響你的判斷。

限制：
- 只能修改 task pack 指定的 write scope
- 不要碰 README / CURRENT_MAINLINE / GRAND_BLUEPRINT / configs/blackcat_004.yaml，除非 prompt 明確要求
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 如果你現在就是要派 `Track S`

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
/Volumes/Samsung SSD/hpa-mdo/docs/task_packs/current_parallel_work/prompts/track_s_explicit_wire_truss_convergence_unblock.md

你的目標是診斷並修掉 inner refresh summary 反覆出現的 `Explicit wire truss Newton solve did not converge`，讓 rerun-aero replay 不要在 explicit wire-truss 這一層就全部掉成 sentinel fallback；不要在同一包裡順手改 rib penalty / ranking 邏輯。

如果本地 repo context 不足，或工具 / solver / library 的行為可能已經變動，可以自行上網查，不要卡在舊文件裡。
上網查時優先看官方文件、solver manual、論文或其他第一手資料，並在回報中簡短說明查了什麼、如何影響你的判斷。

限制：
- 只能修改 `src/hpa_mdo/aero/vsp_aero.py`, `tests/test_vspaero_parser.py`, `tests/test_vspaero_cache.py`
- 不要改 `README.md`, `CURRENT_MAINLINE.md`, `docs/GRAND_BLUEPRINT.md`, `configs/blackcat_004.yaml`
- 每完成一個獨立任務就單獨 commit
- 先做最小必要驗證，再回報結果、風險、未完成處
```

## 什麼時候只寫「做 Track Q」就夠

只有在對方 agent 已經知道這個 repo，或你確定它會先讀 `CURRENT_MAINLINE.md` / `project_state.yaml` 的情況下，才建議只寫：

```text
請照 current_parallel_work task pack 做 Track S。
```

如果是新 agent，或你不確定它會不會自己找文件，請不要只寫這一句，否則很容易理解不完整。

## 推薦做法

- 新 agent：直接貼完整模板
- 已經在這個 repo 工作過的 agent：可以貼短版，再補 task id
- 一次派多個 agent：這一波先不要；先把 Track S 修好、驗過，再決定要不要重跑 Track R
- 如果本地資訊不夠，就允許 agent 主動查官方 / 第一手資料，不要把它綁死在 repo 舊文件
