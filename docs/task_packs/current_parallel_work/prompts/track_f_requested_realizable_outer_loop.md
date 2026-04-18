# Task Prompt: Track F Requested-to-Realizable Outer Loop

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**有限範圍的外圈 shape 調整任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/NOW_NEXT_BLUEPRINT.md`
4. `docs/EXECUTION_ROADMAP.md`

## 任務目標

把 requested-to-realizable 的低維 outer loop 從「手動 sweep 習慣」往「可比較、可總結、可交給 agent」的 workflow 推進。

重點不是 full co-design，而是：

- 先限於低維 knob
- 明確看 requested vs realizable mismatch
- 讓 summary artifact 能支持後續 ranking / iteration
- 讓這條近期版 workflow 更接近：

`low-dimensional aero-shape knob -> inverse design -> jig clearance / mass / manufacturing gate -> discrete layup verdict -> realizable loaded-shape score`

## 推薦 write scope

- `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- `scripts/dihedral_sweep_campaign.py`
- `tests/test_inverse_design.py`
- `docs/task_packs/current_parallel_work/**`

## 完成條件

- 至少一條 low-dimensional outer-loop 路徑有更清楚的 score / summary
- requested 與 realizable 的差距有 machine-readable evidence
- 不把 exact nodal matching 當唯一判準
- discrete layup 或 structural recheck 的最終 verdict 能被 outer-loop summary 消費

## 不要做

- 不改 `src/hpa_mdo/hifi/**`
- 不改 `docs/GRAND_BLUEPRINT.md`
- 不跳進高維 free-form 外形共優化
- 不把離散 layup decision 直接塞進最外圈優化
