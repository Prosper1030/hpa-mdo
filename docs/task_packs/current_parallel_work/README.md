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

這包現在聚焦在 **Phase 2 outer-loop contract realignment：把 AVL spanwise load 接回你原本要的 AVL-first 流程**。

Track U 已經證明：

- AVL `.fs strip force -> SpanwiseLoad` plumbing 是可以接通的
- 但現在的 `candidate_avl_spanwise` 實作**不只加了升力分佈**
- 它還順手改了 load-state / AoA ownership、gate 節奏、以及 recovery 可用性

所以現在更直接的問題不是「AVL 能不能吐展向載荷」，而是：

> 我們需要把 `candidate_avl_spanwise` 收窄回使用者原本要的版本：
> **保留舊 AVL-first outer-loop 節奏，只補 candidate-owned spanwise lift distribution 給結構。**

目前的主任務順序是：

- Track V：已完成，修回 AVL spanwise ownership drift
- Track W：已完成，確認真正 blocker 是 structural selected-state alignment
- Track Y：已完成，把 `candidate_avl_spanwise` 的 structural selected state 對齊回 legacy owner
- Track X：已完成一次，但因為把 `exp = 2.2` 當 baseline，目前只保留為歷史診斷
- Track Z：現在把 repaired AVL-first baseline 拉回 `exp = 1.0`，再重建 canonical shortlist
- Track R：等 Track Z 之後，再用 repaired shortlist 回去做 rib smoke
- Track M / N：只有在 Track R 產生真實 rib 訊號後才開

這一包的目的不是再修 parser，也不是再修 solver，而是把外圈重新收斂成：

`舊 AVL-first 快流程 + candidate-owned AVL spanwise lift distribution -> inverse design / jig / CFRP`

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
- 使用者能清楚知道目前這一波不是單純「改回 AVL」，而是：
  - 先把 `candidate_avl_spanwise` 修回「只補升力分佈 ownership」
  - 再把 structural selected state 對齊回舊流程
  - 再把 baseline exponent 拉回舊主線的 `1.0`
  - 然後才用 repaired AVL-first path 重建 canonical shortlist，回到 Track R / M / N。
