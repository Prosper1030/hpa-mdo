# Task Prompt: Track E Surrogate Warm Start

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**有限範圍的主線加速任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/NOW_NEXT_BLUEPRINT.md`
4. `docs/codex_prompts/surrogate_model_warm_start.md`

## 任務目標

把 surrogate warm start 以 **optional acceleration path** 的方式接回主線。

重點：

- 只做 warm start，不改 physics truth
- 未啟用 surrogate 時，行為保持不變
- 新依賴只能是 optional
- 盡量復用現有 training-data / collector 脈絡

## 推薦 write scope

- `src/hpa_mdo/utils/surrogate.py`
- `src/hpa_mdo/utils/data_collector.py`
- `src/hpa_mdo/structure/optimizer.py`
- `scripts/collect_surrogate_data.py`
- `tests/test_surrogate.py`
- `pyproject.toml`

## 完成條件

- 有可訓練 / 載入 / 推論的 surrogate backend
- optimizer 可以選擇性吃 warm-start 建議點
- 有最小資料收集 / smoke test
- 不啟用 surrogate 時完全 backward compatible

## 不要做

- 不把 surrogate prediction 直接當目標函數
- 不把 sklearn / xgboost 變成必裝
- 不改 `CURRENT_MAINLINE.md`
- 不改 `docs/GRAND_BLUEPRINT.md`
