# Codex Prompts 索引

本目錄保存發給 Codex 5.4 (Extreme High) 執行的「自包含」任務描述。
所有 prompt 都遵守以下規則：

1. **必要的數學、檔案路徑、驗收標準全部寫死在 prompt 內**
   Codex 不需要先 grep 或 read 才知道要做什麼
2. **明確列出「不要做的事」**，避免 Codex 自由發揮 refactor
3. **附 git commit 訊息範本**（繁體中文）

## 任務索引（依優先序）

| 順序 | 檔案 | 狀態 | 預估工時 |
|-----|------|------|---------|
| A | `verify_slsqp_speedup.md` | ⬜ 待派工 | 30 min |
| B | `openmdao_check_partials_test.md` | ⬜ 待派工 | 1 h |
| C | `multi_load_case_optimization.md` | ⬜ 待派工 | 4 h ⚠️ |
| D | `surrogate_model_warm_start.md` | ⬜ 待派工 | 6 h ⚠️ |
| E | `example_output_snapshots.md` | ⬜ 待派工 | 30 min |

## 已完成（保留作為範例）

- `cleanup_low_priority_warnings.md` ✅ 完成於 `0ec4576` / `bfdb0c3` / `a307361`
- `enforce_buckling_in_scipy_path.md` ✅ 完成於 `e6acd35` / `35b0517`

## 給 Claude 的協作備忘

當使用者要派新任務時：
1. 先讀 `docs/codex_tasks.md` 看當前進度
2. 在這裡寫一個 self-contained `<task_name>.md`
3. 把 prompt 內容直接貼回對話讓使用者複製
4. 任務完成後把對應的 .md 移到「已完成」清單，並更新 codex_tasks.md
