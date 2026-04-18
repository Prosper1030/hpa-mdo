# Track T: Ground-Clearance Recovery Outer Loop

## Goal

把目前 rerun-aero replay 裡最直接的 blocker 往前推：

- 不再是 parser/runtime 相容性
- 不再是 explicit wire-truss 假性不收斂
- 而是 **outer-wing jig ground clearance**

這一包的目標不是亂加更多自由度，而是讓 outer-loop 至少能產生：

- 一個 **clearance 明顯改善** 的 candidate，或
- 一個 **非 sentinel 且更接近可比** 的 replay signal

## Why This Exists

Track S 之後，真實 replay 已經能跑到 `analysis complete`，selected candidate 也不再是 solver crash fallback。

但目前 selected candidate 仍然：

- `target_mass_passed = true`
- `overall_feasible = false`
- failure 主要是 `ground_clearance`

而且最低點不是根部，是外翼尾段，集中在：

- rear spar
- near tip / outboard nodes
- `y ≈ 15.8 ~ 16.7 m`

所以這包要處理的是 **outer-loop / candidate 產生邏輯**，不是再修底層 solver。

## Scope

你可以修改：

- `/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_inverse_design.py`
- `/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- `/Volumes/Samsung SSD/hpa-mdo/tests/test_inverse_design.py`

你不可以修改：

- `/Volumes/Samsung SSD/hpa-mdo/README.md`
- `/Volumes/Samsung SSD/hpa-mdo/CURRENT_MAINLINE.md`
- `/Volumes/Samsung SSD/hpa-mdo/docs/GRAND_BLUEPRINT.md`
- `/Volumes/Samsung SSD/hpa-mdo/configs/blackcat_004.yaml`

## What To Implement

優先順序如下：

1. 在不破壞主線 contract 的前提下，加入 **ground-clearance recovery path**
2. 這個 recovery path 應優先從 **低維 outer-loop knob / candidate seed / search bias** 下手
3. 不要把它做成 per-rib combinatorial explosion
4. 不要把這包變成 rib penalty tuning

可接受的方向包括：

- 對 clearance-failing candidate 加入較合理的 uplift / dihedral / target-shape recovery seed
- 在 coarse search / feasibility sweep 中加入專門針對 clearance failure 的 recovery candidate
- 在不破壞目前 mass / shape / manufacturing gate 的前提下，讓 outer-wing jig 不要直接穿地

不建議的方向：

- 再擴 rib 自由度
- 調 hi-fi
- 回頭修 parser
- 回頭修 solver globalization
- 直接把 gate 關掉或把 clearance floor 改鬆

## Success Criteria

至少滿足以下其中之一：

1. 在真 replay 上，`ground_clearance_min_m` 有**明顯改善**
2. 至少出現一個 **非 sentinel 且更可比較** 的 selected-case signal，可供下一輪 `Track R` 使用
3. 如果仍然 fail，也要把 failure 往更真實、更上游的設計限制推進，而不是停在原本同一個 clearance 死點

## Minimum Validation

至少做：

1. 針對新 recovery logic 的最小測試
2. `./.venv/bin/python -m pytest tests/test_inverse_design.py -q` 的合理子集
3. 至少一組真 replay，證明：
   - 沒有回退成 parser / solver crash
   - 能清楚比較修前修後的 clearance 訊號

## Report Back

回報時請明確交代：

- 你選哪一種 recovery 策略
- 為什麼它屬於「解設計問題」，不是「再打一個 patch」
- 最小驗證結果
- 還剩什麼風險
- 這包完成後，下一步應該直接回 `Track R`，還是還要再做一包 clearance refinement
