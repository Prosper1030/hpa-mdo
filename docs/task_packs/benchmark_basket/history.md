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
    - `output/blackcat_004/hifi_dual_beam_production_dedupcheck/structural_check.json`
    - reference 已對齊 `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
    - 結果仍是 `WARN` / `NOT_COMPARABLE`
    - `ROOT/TIP/WIRE` 已可直接長成 mesh NSET，`ROOT clamp nodes=28`、`wire U3 supports=1`
    - analysis deck 已去除完全重複、只差方向的 shell facets，`opposite_normals` 已從 `4762` 降到 `3370`
    - 主要 blocker 仍是 `mesh_quality`，診斷仍含 `nonpositive_jacobian x34`
    - Gmsh `-3` probe 也已明確暴露 root cause：`Invalid boundary mesh (overlapping facets)` / `No elements in volume`
    - 這讓下一步工作更明確：先打 STEP/Gmsh surface 的 mesh robustness，不再優先懷疑 boundary / named-point contract 或 duplicate shell facets
  - 之後又補上一輪 `feat: 補上 hifi mesh diagnostics sidecar 與報告`：
    - 直接從 `spar_jig_shape.step` 開始跑的代表性案例已落在 `output/blackcat_004/hifi_dual_beam_production_stepdiag/`
    - `structural_check.json` 現在會帶出 `mesh_diagnostics`
    - `spar_jig_shape.mesh_diagnostics.json` 會獨立寫出 Gmsh upstream 問題
    - 最新可直接讀到的 issue hints 包含：
      - `overlapping_boundary_mesh x1`
      - `no_elements_in_volume x1`
      - `duplicate_boundary_facets x2`
      - `invalid_surface_elements x38`
      - `equivalent_triangles x2128`
      - `duplicate_shell_facets x599`
    - 這代表 Mac hi-fi 現在不只知道「CalculiX 因 mesh_quality fail」，也能在 report 裡直接指出較上游的 STEP/Gmsh 問題來源
  - 接著補上 `fix: 補上 gmsh OCC healing wrapper` 與 `fix: 放寬 coarse mesh named point 容差`：
    - STEP meshing 現在會先套 `HealShapes + Coherence`
    - 還是維持最多一次 coarse retry，不會無限重試
    - healed mesh sidecar 已改善成：
      - `invalid_surface_elements x12`
      - `equivalent_triangles x340`
      - `duplicate_shell_facets x259`
    - 先前的
      - `overlapping_boundary_mesh x1`
      - `no_elements_in_volume x1`
      - `duplicate_boundary_facets x2`
      已不再出現
    - coarse healed mesh 仍可保住 `ROOT/TIP/WIRE_1` NSET
    - healed mesh 再進 CalculiX 後，solver diagnostics 也從
      - `opposite_normals x3370`
      - `nonpositive_jacobian x34`
      改善成
      - `opposite_normals x732`
      - `nonpositive_jacobian x10`
    - 這代表 OCC healing 對現在的主 blocker 是有效的，但還不足以讓 Mac hi-fi 升格成 benchmark-ready
