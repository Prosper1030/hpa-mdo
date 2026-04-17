# Current Parallel Work Task Pack

> 這包文件是給多個 AI agent 並行協作用的最小上下文集合。  
> 目標不是重新解釋整個 repo，而是讓 agent 快速知道：現在正式主線是什麼、這包裡有哪些可平行任務、自己該讀哪些文件、不能碰哪些檔案。

## Read Order

所有 agent 進來後，先照這個順序讀：

1. [CURRENT_MAINLINE.md](../../../CURRENT_MAINLINE.md)
2. [project_state.yaml](../../../project_state.yaml)
3. [docs/README.md](../../README.md)
4. [docs/NOW_NEXT_BLUEPRINT.md](../../NOW_NEXT_BLUEPRINT.md)
5. 只讀自己被分派的 prompt 檔

## What This Pack Covers

這包只涵蓋目前最適合平行處理、且 write set 可以拆開的工作：

- Track B：inverse-design validity / gate
- Track C：Mac structural spot-check
- Track D：discrete layup 主線化

## How To Use This Pack

- 你給 agent 的最小指令應該是：
  - 先讀上面的 `Read Order`
  - 再讀一份指定 prompt
  - 然後只在 prompt 允許的檔案範圍內工作
- 如果你想直接把任務貼給另一個 agent，請優先用 [HANDOFF_QUICKSTART.md](HANDOFF_QUICKSTART.md) 裡的現成模板。
- 如果 agent 要改 `README.md`、`CURRENT_MAINLINE.md`、`docs/GRAND_BLUEPRINT.md` 或 `configs/blackcat_004.yaml`，應先停下來，不要自行擴張範圍。
- 如果 agent 發現 prompt 與 `CURRENT_MAINLINE.md` 衝突，以 `CURRENT_MAINLINE.md` 為準。

## Success Criteria

- 每個 agent 可以在 5 分鐘內知道自己該做什麼、不該碰什麼。
- 不需要重新閱讀大量歷史報告。
- 不同 agent 的 write set 不互相打架。
