# Benchmark Basket Task Pack

> 這包文件是給「整理可比驗證案例」用的最小上下文集合。
> 目標不是立刻把某個舊 APDL / ANSYS case 升格成唯一真值，而是讓 agent 能系統性整理現在有哪些案例、哪些還值得用、哪些只適合當歷史 evidence。

## Read Order

所有 agent 進來後，先照這個順序讀：

1. [CURRENT_MAINLINE.md](../../../CURRENT_MAINLINE.md)
2. [project_state.yaml](../../../project_state.yaml)
3. [docs/README.md](../../README.md)
4. [docs/hi_fidelity_validation_stack.md](../../hi_fidelity_validation_stack.md)
5. 只讀自己被分派的 prompt 檔

## What This Pack Covers

這包只處理 benchmark basket 本身，不直接修改主線 solver：

- 歷史 ANSYS / APDL / SyncFile case 盤點
- 本地 `output/` 與 `SyncFile/` 的可比案例篩選
- benchmark metadata / candidate basket 建議
- 哪些案例適合做 Mac structural spot-check 對照

目前最重要的輸出文件：

- [benchmark_candidates.md](benchmark_candidates.md)
- [history.md](history.md)

## How To Use This Pack

- 你給 agent 的最小指令應該是：
  - 先讀上面的 `Read Order`
  - 再讀一份指定 prompt
  - 然後只在 prompt 允許的檔案範圍內工作
- 如果 agent 想直接改 `scripts/direct_dual_beam_inverse_design.py`、`src/hpa_mdo/hifi/**` 或 `README.md`，應先停下來；這包的任務主要是整理 benchmark basket，不是直接改 solver。
- 如果 agent 發現舊報告與 `CURRENT_MAINLINE.md` 衝突，以 `CURRENT_MAINLINE.md` 為準。

## Success Criteria

- 不會先把某一份舊 APDL case 釘死成唯一 benchmark。
- 可以列出目前最值得保留的可比案例清單與理由。
- 可以給 Mac structural spot-check 一個「先從哪幾個案例比起」的建議順序。
