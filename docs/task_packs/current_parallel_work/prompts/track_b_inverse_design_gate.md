# Task Prompt: Track B Inverse-Design Gate

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**有限範圍的主線實作任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/task_packs/current_parallel_work/README.md`

## 任務目標

把 inverse-design 的 validity / gate 結果整理成更容易被人與 agent 直接消化的輸出。

重點不是重寫 physics，而是把 repo 目前已有的：

- loaded-shape mismatch
- target-shape error
- ground clearance
- manufacturing
- feasibility / failures

收成更清楚的 machine-readable artifact。

## 推薦 write scope

- `scripts/direct_dual_beam_inverse_design.py`
- `src/hpa_mdo/structure/inverse_design.py`
- `tests/test_inverse_design.py`

## 完成條件

- inverse-design run 會多一份清楚的 validity summary artifact
- artifact 會被 summary JSON / report 正確引用
- 不引入新的主線敘事混亂
- 至少有對應測試

## 不要做

- 不改 `README.md`
- 不改 `CURRENT_MAINLINE.md`
- 不改 `docs/GRAND_BLUEPRINT.md`
- 不擴張成 full nonlinear rewrite
- 不把 producer / decision interface 混回主 physics
