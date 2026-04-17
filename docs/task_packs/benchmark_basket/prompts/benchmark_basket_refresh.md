# Task Prompt: benchmark_basket_refresh

## Goal

整理 repo 目前可用的高保真 / ANSYS / APDL benchmark 候選，不要先把任何單一歷史 case 寫死成唯一真值。

## Required Context

開始前至少先讀：

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/hi_fidelity_validation_stack.md`
4. `docs/task_packs/benchmark_basket/README.md`
5. `docs/task_packs/benchmark_basket/TASKS.md`

## What To Do

1. 盤點 `output/`、`SyncFile/`、`docs/` 中已存在的 dual-beam / dual-spar / ANSYS / APDL compare summary。
2. 整理哪些案例：
   - 定義清楚
   - 可重現或至少可追溯
   - 與現在 dual-beam / jig-oriented 主線仍有可比性
3. 標記哪些案例只適合當歷史 evidence，哪些可以進當前 `benchmark basket`。
4. 若有需要，可更新 `docs/hi_fidelity_validation_stack.md` 中 benchmark policy 或推薦比較順序，但不要把單一 case 寫成唯一 gate。

## Write Scope

你只能修改：

- `docs/task_packs/benchmark_basket/**`
- `docs/hi_fidelity_validation_stack.md`

## Deliverables

- 一份 benchmark 候選清單
- 至少包含：
  - case 名稱
  - 路徑
  - 類型（historical evidence / current candidate / weak evidence）
  - 可比較的指標
  - 是否推薦給 Mac structural spot-check 當第一批對照

## Guardrails

- 不要改 solver
- 不要改 inverse-design 主線
- 不要把歷史 parity case 說成現在唯一真值
- 如果證據不足，應清楚標成 `uncertain`，不要硬下結論
