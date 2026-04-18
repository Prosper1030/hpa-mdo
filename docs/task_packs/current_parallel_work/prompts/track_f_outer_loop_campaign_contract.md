# Task Prompt: Track F Outer-Loop Campaign Contract

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**低維 outer-loop 契約收斂任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/dual_beam_recipe_library_architecture.md`

## 任務目標

把低維 outer-loop / campaign 層整理得更像正式選 design 的工具，而不是零散 sweep。

重點是：

- 支援比較大的 quick-analysis search budget
- 把 candidate score / reject reason 說清楚
- 幫後續 discrete final-design verdict 接回 outer loop 鋪路

## 推薦 write scope

- `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- `scripts/dihedral_sweep_campaign.py`
- `tests/test_inverse_design.py`

## 完成條件

- campaign / sweep artifact 能清楚表達 candidate score
- quick-analysis 的 search budget 不再被寫死得太保守
- summary 至少能表達：
  - requested knobs
  - realizable mismatch
  - jig clearance / mass gate
  - candidate reject reason 或 winner evidence

## 不要做

- 不要碰 `src/hpa_mdo/structure/material_proxy_catalog.py`
- 不要碰 `src/hpa_mdo/utils/discrete_layup.py`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
