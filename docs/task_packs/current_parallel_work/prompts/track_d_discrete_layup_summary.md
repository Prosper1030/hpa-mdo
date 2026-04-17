# Task Prompt: Track D Discrete Layup Summary

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**有限範圍的離散複材主線任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/task_packs/current_parallel_work/README.md`

## 任務目標

把 discrete layup 從「已存在的能力」更明確提升成「主線 final design output」。

## 推薦 write scope

- `examples/blackcat_004_optimize.py`
- `src/hpa_mdo/utils/discrete_layup.py`
- `tests/test_discrete_layup*.py`

## 完成條件

- 產生更適合 final design 解讀的 layup summary
- 清楚區分 continuous warm-start 與 discrete final output
- 至少有對應測試

## 不要做

- 不碰 `src/hpa_mdo/hifi/**`
- 不碰 `scripts/direct_dual_beam_inverse_design.py`
- 不把連續 thickness optimum 寫回 final answer
