# Task Prompt: Track Q VSPAero `.lod` Parser Compatibility Fix

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**獨立 patch 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`
7. `src/hpa_mdo/aero/vsp_aero.py`
8. `tests/test_vspaero_parser.py`
9. `tests/test_vspaero_cache.py`

## 任務目標

修掉 `candidate_rerun_vspaero` 在 OpenVSP 3.45.3 下的 `.lod` parser 相容性 bug。

這次要解的不是 rib 邏輯，也不是 inverse-design 本身，而是：

- 現行 parser 假設舊的 16-column `.lod` schema
- 新的 OpenVSP 3.45.3 `.lod` 是 60+ column
- parser fallback 仍沿用舊固定索引，錯把 `Zavg` 當 `Chord`
- 最後觸發 `SpanwiseLoad.chord must be strictly positive`

## 你要做到的事

1. `VSPAeroParser` 不再依賴固定 16-column 索引當唯一 schema。
2. 解析時優先依 header 名稱動態對欄位。
3. 同時支援：
   - 舊的 `Wing S Xavg Yavg Zavg Chord ...` 格式
   - OpenVSP 3.45.3 這種 `Iter VortexSheet TrailVort Xavg Yavg Zavg dSpan SoverB Chord ...` 格式
4. 不能再把 `Zavg` 當 `Chord`、把 `Xavg` 當 `Yavg`。
5. 補 regression tests，至少覆蓋：
   - 新格式 header + numeric rows 可成功 parse
   - `chord` 全正
   - `y` 仍為半翼正向遞增
   - cache 測試仍過

## 最低要求

- 優先在既有 `tests/test_vspaero_parser.py` 與 `tests/test_vspaero_cache.py` 補測試
- 如果需要，可以把新格式 sample `.lod` 片段直接寫在測試字串裡
- 不要把這一包擴張成 load mapping、inverse-design、rib tuning 任務
- 不要順手改 `scripts/direct_dual_beam_inverse_design.py`

## 推薦 write scope

- `src/hpa_mdo/aero/vsp_aero.py`
- `tests/test_vspaero_parser.py`
- `tests/test_vspaero_cache.py`

## 驗證要求

至少跑：

1. `./.venv/bin/python -m pytest tests/test_vspaero_parser.py tests/test_vspaero_cache.py`
2. 如果有必要，再補一個最小 smoke：
   - 用測試中的新格式 sample `.lod` 實際 parse 一次，確認 `SpanwiseLoad.chord` 全正

## 回報時要講清楚

1. 你是怎麼辨識新舊 header 的
2. 新格式 `.lod` 現在對到哪些欄位
3. 你補了哪些 regression tests
4. 還有沒有殘留風險
5. 這包做完後，是否足以重跑 Track P

## 不要做

- 不要改 `scripts/**`
- 不要改 `src/hpa_mdo/structure/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
- 不要改 `configs/blackcat_004.yaml`
