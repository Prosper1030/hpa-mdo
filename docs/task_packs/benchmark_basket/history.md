# Benchmark Basket History

## 2026-04-17

- 初版 benchmark basket 盤點完成。
- 目前先把案例分成三類：
  - `current_candidate`
  - `historical_evidence`
  - `not_yet_ready`
- 初步結論：
  - `dual_beam_production_check` 最接近現在 dual-beam 主線，但仍是 inspection-only，不是 hard gate。
  - `dual_spar_spotcheck` 與其 neighbors 對理解 model-form risk 很有價值，但它們屬於 legacy dual-spar family，不該再被寫成唯一 benchmark 真值。
  - `dual_beam_refinement` 對「局部設計朝更硬版本移動後，dual-beam / eq / ANSYS 的相對關係」很有參考價值，但仍不夠升格成唯一 sign-off case。
  - Mac `structural_check` 經過 `feat: 強化 Mac hifi structural spot-check 診斷輸出` 後，已具備更好的 comparability / issue-category 診斷能力。
  - fresh representative run 已完成：
    - `output/blackcat_004/hifi_dual_beam_production_syncfile_reference/structural_check.json`
    - reference 已對齊 `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
    - 結果仍是 `WARN` / `NOT_COMPARABLE`
    - 主要 blocker 仍是 `mesh_quality`，診斷為 `opposite_normals x4762` 與 `nonpositive_jacobian x32`
