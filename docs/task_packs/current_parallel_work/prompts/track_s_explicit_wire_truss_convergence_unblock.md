# Task Prompt: Track S Explicit Wire-Truss Convergence Unblock

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**核心 solver patch 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`
6. `src/hpa_mdo/structure/dual_beam_mainline/solver.py`
7. `tests/test_dual_beam_mainline.py`
8. `tests/test_inverse_design.py`

## 任務目標

修掉現在 rerun-aero replay 內層 refresh summary 反覆出現的：

`RuntimeError: Explicit wire truss Newton solve did not converge`

這一包的核心不是 rib ranking，不是 parser，也不是 hi-fi。
這一包只回答一件事：

**為什麼 explicit wire-truss Newton / line search 在目前 candidate rerun 路徑下系統性失敗，並把它修到至少不再卡死這些 replay。**

## 最低要求

- 先重現或萃取目前的失敗模式
- 修正點優先落在：
  - `src/hpa_mdo/structure/dual_beam_mainline/solver.py`
- 至少補一個 solver-level regression test
- 如果需要，補一個最小 inverse-design regression，證明同一路徑不再死在同一個 wire-truss convergence 點
- 不要把這包偷換成 rib penalty / ranking / parser 任務

## 可接受的解法方向

你可以選合理的一條，但要明確說明你選哪條：

1. 真的修掉 Newton / line search 收斂問題
2. 如果某些 failure mode 物理上合理但數值上太硬，可以把它降成**bounded / diagnosable failure**，避免整個 replay 直接掉成無資訊 sentinel

但不管選哪條，都必須：

- 保留 production 主線的工程邊界
- 不要把明顯錯誤硬吞掉
- 不要只靠放寬容差假裝問題消失

## 推薦 write scope

- `src/hpa_mdo/structure/dual_beam_mainline/solver.py`
- `tests/test_dual_beam_mainline.py`
- `tests/test_inverse_design.py`

## 驗證要求

最少要有：

1. 你新增或更新的 solver-level test
2. 一組最小 inverse-design / rerun replay regression
3. 回報：
   - 修前怎麼失敗
   - 修後怎麼改善
   - 還剩哪些邊界沒處理

## 不要做

- 不要改 `README.md`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
- 不要改 `configs/blackcat_004.yaml`
- 不要在同一包裡調 rib penalty / family cap / surrogate 權重
- 不要把 hi-fi / validation 任務混進來
