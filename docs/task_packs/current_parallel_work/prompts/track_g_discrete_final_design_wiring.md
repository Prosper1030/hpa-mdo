# Task Prompt: Track G Discrete Final-Design Wiring

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**主線輸出整合任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/dual_beam_recipe_library_architecture.md`

## 任務目標

讓主線輸出更清楚地表達 discrete final design verdict，讓後續 outer loop 與 handoff 更自然地吃得到它。

## 推薦 write scope

- `examples/blackcat_004_optimize.py`
- `src/hpa_mdo/utils/visualization.py`
- `tests/test_optimizer_buckling.py`
- `tests/test_discrete_layup.py`

## 完成條件

- optimization / summary artifact 更明確暴露 discrete final-design verdict
- 結果裡能更容易看出：
  - overall discrete status
  - structural recheck
  - 對選 design 有用的 pass / fail 訊號

## 不要做

- 不要碰 `src/hpa_mdo/structure/material_proxy_catalog.py`
- 不要碰 `src/hpa_mdo/utils/discrete_layup.py`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
