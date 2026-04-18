# Current Parallel Work Task Pack

> 這包文件是給多個 AI agent 並行協作用的最小上下文集合。  
> 目標不是重新解釋整個 repo，而是讓 agent 快速知道：現在正式主線是什麼、這包裡有哪些可平行任務、自己該讀哪些文件、不能碰哪些檔案。

## Read Order

所有 agent 進來後，先照這個順序讀：

1. [CURRENT_MAINLINE.md](../../../CURRENT_MAINLINE.md)
2. [project_state.yaml](../../../project_state.yaml)
3. [docs/TARGET_STANDARD_GAP_MAP.md](../../TARGET_STANDARD_GAP_MAP.md)
4. [docs/RIB_INTEGRATION_PLAN.md](../../RIB_INTEGRATION_PLAN.md)
5. [docs/README.md](../../README.md)
6. [docs/NOW_NEXT_BLUEPRINT.md](../../NOW_NEXT_BLUEPRINT.md)
7. 只讀自己被分派的 prompt 檔

## What This Pack Covers

這包現在聚焦在 **Phase 2.8 solver unblock：explicit wire-truss convergence**。

上一波 parser/runtime unblock 已經完成，`candidate_rerun_vspaero` 也已經能跑到真實 summary；Track R 的多 seed smoke 則把 immediate blocker 再往下縮到 explicit wire-truss Newton / line search 收斂。

目前的主任務是：

- Track S：explicit wire-truss convergence unblock

這一包的目的不是再跑更多 smoke，也不是直接調 rib penalty，而是先把 inner refresh summary 裡反覆出現的 `Explicit wire truss Newton solve did not converge` 解掉。

## How To Use This Pack

- 你給 agent 的最小指令應該是：
  - 先讀上面的 `Read Order`
  - 再讀一份指定 prompt
  - 然後只在 prompt 允許的檔案範圍內工作
- 如果你想直接把任務貼給另一個 agent，請優先用 [AGENT_LAUNCH_PLAN.md](AGENT_LAUNCH_PLAN.md) 或 [HANDOFF_QUICKSTART.md](HANDOFF_QUICKSTART.md) 裡的現成模板。
- 如果 agent 要改 `README.md`、`CURRENT_MAINLINE.md`、`docs/GRAND_BLUEPRINT.md` 或 `configs/blackcat_004.yaml`，應先停下來，不要自行擴張範圍。
- 如果 agent 發現 prompt 與 `CURRENT_MAINLINE.md` 衝突，以 `CURRENT_MAINLINE.md` 為準。
- 如果本地 repo 資訊不夠，或工具 / solver / library 的事實可能已經變動，agent 可以自行上網查，不要卡在舊文件裡。
- 上網查時優先看官方文件、solver manual、論文或其他第一手資料，並在回報裡簡短說明查了什麼、改變了什麼判斷。

## Success Criteria

- 每個 agent 可以在 5 分鐘內知道自己該做什麼、不該碰什麼。
- 不需要重新閱讀大量歷史報告。
- 不同 agent 的 write set 不互相打架。
- 使用者能清楚知道目前這一波不是再加模型、也不是再修 parser，而是先把 explicit wire-truss 收斂問題解掉，之後再重跑更有訊號的 rib smoke。
