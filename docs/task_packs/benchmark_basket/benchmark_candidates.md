# Benchmark Basket Candidates

> 這份文件整理目前 repo 與 `SyncFile` 中最值得保留的高保真 / ANSYS / APDL 對照案例。
> 目的不是選出唯一真值，而是定義一個**可更新的 benchmark basket**，讓後續 Mac structural spot-check 與 dual-beam 主線驗證有一致的起點。

## Basket Policy

- 不把任何單一歷史 APDL / ANSYS case 寫成唯一 sign-off gate。
- 優先保留：
  - 定義清楚
  - 路徑固定
  - 指標清楚
  - 與現在 dual-beam / jig-oriented 主線仍有可比性的案例
- 明確區分：
  - `current_candidate`
  - `historical_evidence`
  - `not_yet_ready`

## Recommended Order

1. 先用 `dual_beam_production_check` 當目前最接近主線的 ANSYS inspection reference。
2. 用 `dual_beam_refinement` 當「局部幾何變硬後是否仍維持相似判斷」的補充 evidence。
3. 用 `dual_spar_spotcheck` 與其 neighbors 當 legacy model-form risk package，不當唯一 benchmark gate。
4. Mac high-fidelity 已有 fresh representative run，而且 `ROOT/TIP/WIRE` 的 NSET / boundary mapping 已對齊；但在 mesh-quality 收斂前，仍先維持 `not_yet_ready`。

## Candidate Table

| Case | Bucket | Why keep it | Key metrics now | Recommended use |
|---|---|---|---|---|
| `blackcat_004_dual_beam_production_check` | `current_candidate` | 最接近目前 dual-beam production 主線；已有固定 ANSYS compare 路徑 | main tip deflection error `19.21%`、total support reaction error `11.34%`、mass error `0.19%`；目前定位 `INFO ONLY` | 當前最適合的 ANSYS inspection reference，但不要當 hard gate |
| `blackcat_004_dual_beam_refinement` | `historical_evidence` | 保留了 warm/refined eq/dual 對照，也有 refined ANSYS spot-check summary | refined eq mass `9.871 kg`、refined dual mass `9.872 kg`；ANSYS refined spot-check 仍是 `MODEL-FORM RISK` | 用來觀察「往更硬設計移動後」相對趨勢是否一致 |
| `blackcat_004_dual_spar_spotcheck` | `historical_evidence` | 最完整的 legacy dual-spar baseline 對照案例 | tip deflection error `14.14%`、max \|UZ\| error `35.64%`、support reaction error `0.00%`、mass error `0.19%`；整體 `MODEL-FORM RISK` | 保留作 model-form risk baseline，不再當唯一 benchmark 真值 |
| `blackcat_004_dual_spar_spotcheck_neighbors` | `historical_evidence` | baseline / harder / softer 三點一起看，能評估 ranking flip 風險 | baseline `9.454 kg / 2500 mm`、harder `9.744 kg / 2274 mm`、softer `9.164 kg / 2756 mm`；各點 ANSYS compare 仍是 `MODEL-FORM RISK` | 當 sensitivity package，用來看接近設計是否可能因 hi-fi 對照而翻盤 |
| `output/blackcat_004/hifi_heal_structcheck` | `not_yet_ready` | 本機 Mac structural stack 已有正式入口，而且現在 STEP meshing 會先經過 OCC healing wrapper（`HealShapes + Coherence`），再配 bounded coarse fallback；`ROOT/TIP/WIRE` 仍可直接寫成 mesh NSET | fresh representative JSON 仍是 `WARN` / `NOT_COMPARABLE`，但 `mesh_diagnostics` 已從 `overlapping_boundary_mesh x1 / no_elements_in_volume x1 / duplicate_boundary_facets x2 / invalid_surface_elements x38 / duplicate_shell_facets x599` 改善成 `invalid_surface_elements x12 / equivalent_triangles x340 / duplicate_shell_facets x259`；CalculiX diagnostics 也從 `opposite_normals x3370 / nonpositive_jacobian x34` 降到 `x732 / x10` | 保留成最新本機診斷證據；現在已證明 OCC healing 有價值，下一步應聚焦剩下的 invalid facets / equivalent triangles / shell duplication，而不是回頭重查 boundary contract |

## Evidence Notes

### 1. `blackcat_004_dual_beam_production_check`

- Paths:
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/production_vs_dual_spar_ansys_surrogate.txt`
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
- Why it matters:
  - 它是目前最接近 dual-beam production 主線的 ANSYS compare。
  - 雖然對照的是 ANSYS surrogate，而不是完整 final truth，但已經比 legacy equivalent-beam baseline 更接近現在 workflow。
- Current caution:
  - 報告自己明確寫 `INFO ONLY`。
  - support reaction 與 main tip deflection 差距仍大，不能被過度宣稱為 already-close。

### 2. `blackcat_004_dual_beam_refinement`

- Paths:
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_refinement/dual_beam_refinement_report.txt`
  - `/Volumes/Samsung SSD/hpa-mdo/output/_archive_pre_2026_04_15/blackcat_004_dual_beam_refinement/ansys_refined/spotcheck_summary.txt`
- Why it matters:
  - 它記錄了一條「從 warm baseline 往更硬、較低 deflection 設計移動」的最小可讀 refinement path。
  - `refined eq mass` 與 `refined dual mass` 幾乎一致，對理解 dual-beam local refinement 的方向很有幫助。
- Current caution:
  - refined ANSYS spot-check 仍是 `MODEL-FORM RISK`。
  - 更適合當趨勢證據，不適合當唯一 gate。

### 3. `blackcat_004_dual_spar_spotcheck`

- Path:
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_spar_spotcheck/ansys/spotcheck_compare_summary.txt`
- Why it matters:
  - 這是目前最完整、最清楚的 legacy dual-spar baseline 案例。
  - 對支承反力與質量的對照非常乾淨，仍有工程價值。
- Current caution:
  - 它的 structural family 與現在正式 dual-beam inverse-design 主線已有距離。
  - 應降級成 historical evidence，不再是 sign-off 主角。

### 4. `blackcat_004_dual_spar_spotcheck_neighbors`

- Paths:
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_spar_spotcheck_neighbors/point_summary.txt`
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_spar_spotcheck_neighbors/baseline/ansys/spotcheck_compare_summary.txt`
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_spar_spotcheck_neighbors/harder_+3pct_od/ansys/spotcheck_compare_summary.txt`
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_spar_spotcheck_neighbors/softer_-3pct_od/ansys/spotcheck_compare_summary.txt`
- Why it matters:
  - 單一 baseline 看不到 ranking flip 風險，neighbor package 才看得到。
  - 它能回答「在更硬 / 更軟的近鄰設計裡，高保真對照是否可能改變你對設計排序的直覺」。
- Current caution:
  - 仍然是 legacy dual-spar family。
  - 更適合當 sensitivity evidence，而不是新主線的唯一 benchmark。

### 5. `output/blackcat_004/hifi_heal_structcheck`

- Paths:
  - `/Volumes/Samsung SSD/hpa-mdo/output/blackcat_004/hifi_heal_structcheck/structural_check.md`
  - `/Volumes/Samsung SSD/hpa-mdo/output/blackcat_004/hifi_heal_structcheck/structural_check.json`
  - `/Volumes/Samsung SSD/hpa-mdo/output/blackcat_004/hifi_heal_probe/spar_jig_shape.mesh_diagnostics.json`
  - `src/hpa_mdo/hifi/structural_check.py`
- Why it matters:
  - 本機 Mac route 是未來最值得持續投資的 validation path。
  - 最新 code 已支援 `structural_check.json`、`mesh_diagnostics` sidecar、`comparability`、`issue_category` 與更明確的 solver diagnostics。
  - STEP meshing 現在會先經過 OCC healing wrapper（`HealShapes + Coherence`），而且仍維持最多一次 coarse retry，不會無上限重試。
  - `ROOT/TIP/WIRE` 現在已直接由 spanwise matching 寫成 NSET，不再依賴舊的 `(x,y,z)` 最近點假設。
  - analysis deck 現在也會去除完全重複、只差方向的 shell facets。
  - 這次 fresh representative healed run 已把 reference 對齊到：
    `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
- Current caution:
  - fresh run 仍是 `WARN` / `NOT_COMPARABLE`。
  - `ROOT clamp nodes=35`、`wire U3 supports=1` 已合理化，代表 boundary contract 這一層仍維持乾淨。
  - OCC healing 後，mesh sidecar 已不再出現：
    - `overlapping_boundary_mesh`
    - `no_elements_in_volume`
    - `duplicate_boundary_facets`
  - 但 static 與 buckle 仍停在 `mesh_quality`，診斷仍含 `opposite_normals x732` 與 `nonpositive_jacobian x10`。
  - 這代表目前最該修的是剩下的 invalid facets / equivalent triangles / shell duplication，而不是再回頭重查 named-point / boundary contract。

## Practical Recommendation

- 如果今天要選一個最先拿來和 Mac structural spot-check 對齊的外部 reference，先選 `blackcat_004_dual_beam_production_check`。
- 如果要看 design ordering / sensitivity，再加上 `dual_spar_spotcheck_neighbors`。
- 如果要做 repo 歷史脈絡或風險對照，再保留 `dual_spar_spotcheck` baseline。
- Mac `structural_check` 現在已經有 fresh representative run，而且 boundary/NSET contract 與 duplicate shell facet 去重都已對齊；它目前證明的是「主要 blocker 已收斂成 STEP/Gmsh surface 的 mesh-quality」，不是「已可直接升格成 benchmark candidate」。
