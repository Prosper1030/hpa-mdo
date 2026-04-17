# Task Prompt: Track C Mac Structural Spot-Check

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**有限範圍的高保真驗證任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/hi_fidelity_validation_stack.md`
4. `docs/task_packs/current_parallel_work/README.md`

## 任務目標

把 Apple Silicon 上的 `Gmsh -> CalculiX -> report` 路線收斂成更可信的 local structural spot-check。

重要：

- `crossval_report.txt` 可以當 inspection / workflow-debug reference。
- 不要把它當成 external validation truth。
- 如果沒有 apples-to-apples external benchmark，就不要宣稱這條線已完成 validation。

## 推薦 write scope

- `src/hpa_mdo/hifi/**`
- `scripts/hifi_*`
- `tests/test_hifi_*`

## 完成條件

- 更清楚地區分 mesh / BC / load-mapping / solver 問題
- 改善 structural check 的可診斷性或可比較性
- 至少有對應測試

## 不要做

- 不把這條線宣稱成最終真值
- 不把 internal crossval report 靠近程度寫成 validation 完成度
- 不碰 `scripts/direct_dual_beam_inverse_design.py`
- 不修改主線文件去誇大目前高保真能力
