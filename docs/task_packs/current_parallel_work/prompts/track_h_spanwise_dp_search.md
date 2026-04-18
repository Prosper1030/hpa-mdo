# Task Prompt: Track H Spanwise DP Discrete Search

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**第二波離散搜尋任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/dual_beam_recipe_library_architecture.md`

## 前提

這一包只有在 **Track E recipe library foundation 已經 merge 並驗證** 之後才應開始。

如果你發現 repo 裡的 recipe-library contract 仍不穩，請停下來回報，不要自行擴張假設。

## 任務目標

把 spanwise discrete layup selection 正式變成搜尋問題，而不是逐段 first-fit round-up。

正式方向：

- 優先考慮 DP / shortest-path 類方法
- 不要先跳去高成本 GA

## 推薦 write scope

- `src/hpa_mdo/utils/discrete_spanwise_search.py`
- `src/hpa_mdo/utils/discrete_layup.py`
- `tests/test_discrete_spanwise_search.py`
- `tests/test_discrete_layup.py`

## 完成條件

- 有可測試的 spanwise DP / shortest-path search 模組
- discrete layup 不再只有逐段 local round-up
- transition / manufacturability rule 至少有基本測試保護

## 不要做

- 不要碰 `src/hpa_mdo/structure/material_proxy_catalog.py`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
