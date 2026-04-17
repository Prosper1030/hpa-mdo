# Benchmark Basket Candidates

> 這份文件整理目前 repo 與 `SyncFile` 中最值得保留的高保真 / ANSYS / APDL 對照案例。
> 目的不是選出唯一真值，而是定義一個**可更新的 benchmark basket**，讓後續 Mac structural spot-check 與 dual-beam 主線驗證有一致的起點。
> **重要澄清**：`crossval_report.txt` 是 internal inspection reference / export contract，不是獨立 validation truth。任何拿它做 compare 的工作，都應先寫成 inspection / workflow debug，而不是 external validation。

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

1. 先用 `dual_beam_production_check` 當目前最接近主線的 ANSYS inspection reference，不把它升格成真值。
2. 用 `dual_beam_refinement` 當「局部幾何變硬後是否仍維持相似判斷」的補充 evidence。
3. 用 `dual_spar_spotcheck` 與其 neighbors 當 legacy model-form risk package，不當唯一 benchmark gate。
4. Mac high-fidelity 已有 fresh representative run，而且 `ROOT/TIP/WIRE` 的 NSET / boundary mapping 已對齊；但在 mesh-quality 收斂前，仍先維持 `not_yet_ready`。

## Candidate Table

| Case | Bucket | Why keep it | Key metrics now | Recommended use |
|---|---|---|---|---|
| `blackcat_004_dual_beam_production_check` | `current_candidate` | 最接近目前 dual-beam production 主線；已有固定 compare 路徑，但本質上仍是 internal inspection reference | main tip deflection error `19.21%`、total support reaction error `11.34%`、mass error `0.19%`；目前定位 `INFO ONLY` | 當前最適合的 inspection reference，但不要當 hard gate，更不要當 external truth |
| `blackcat_004_dual_beam_refinement` | `historical_evidence` | 保留了 warm/refined eq/dual 對照，也有 refined ANSYS spot-check summary | refined eq mass `9.871 kg`、refined dual mass `9.872 kg`；ANSYS refined spot-check 仍是 `MODEL-FORM RISK` | 用來觀察「往更硬設計移動後」相對趨勢是否一致 |
| `blackcat_004_dual_spar_spotcheck` | `historical_evidence` | 最完整的 legacy dual-spar baseline 對照案例 | tip deflection error `14.14%`、max \|UZ\| error `35.64%`、support reaction error `0.00%`、mass error `0.19%`；整體 `MODEL-FORM RISK` | 保留作 model-form risk baseline，不再當唯一 benchmark 真值 |
| `blackcat_004_dual_spar_spotcheck_neighbors` | `historical_evidence` | baseline / harder / softer 三點一起看，能評估 ranking flip 風險 | baseline `9.454 kg / 2500 mm`、harder `9.744 kg / 2274 mm`、softer `9.164 kg / 2756 mm`；各點 ANSYS compare 仍是 `MODEL-FORM RISK` | 當 sensitivity package，用來看接近設計是否可能因 hi-fi 對照而翻盤 |
| `output/blackcat_004/hifi_support_reaction_rerun_20260418` | `not_yet_ready` | 本機 Mac structural stack 已有正式入口，而且現在 STEP meshing 會先經過 OCC healing wrapper（`HealShapes + Coherence`），再配 bounded coarse fallback；analysis deck 也加入 shell normals consistency 與極低品質 sliver shell 過濾；`spar_data.csv` 已升級成 spatial main/rear load replay、優先對齊指定 summary 所在 evidence root，wire support 也會優先對齊同一份 CSV 的 main spar 幾何位置，並在必要時收成小範圍 local cluster；support reaction compare 也已進入正式報告/JSON | fresh representative JSON 現在已不再是純 `mesh_quality fail`：`static` 進到 `COMPARABLE`、`support_reactions` 也進到 `COMPARABLE`、`buckle` 可完成，`overall_comparability = LIMITED`；static tip deflection 已從 `4.7992 m` 收斂到 `2.55449 m`，相對 reference `2.39372 m` 的差距約 `6.72%`，而 total support reaction 相對 reference `817.782 N` 的差距只剩約 `0.00284%`，但目前仍先保留在 benchmark basket，不急著升格成 hard gate | 保留成最新本機診斷證據；現在最主要的 blocker 已從「solver 直接炸」轉成「shell / section / support completeness 與 reference 還不對齊」 |

## Evidence Notes

### 1. `blackcat_004_dual_beam_production_check`

- Paths:
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/production_vs_dual_spar_ansys_surrogate.txt`
  - `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
- Why it matters:
  - 它是目前最接近 dual-beam production 主線的 ANSYS compare。
  - 但 `crossval_report.txt` 本質上仍是 internal expected-results / export contract，不是獨立高保真真值。
  - 它能幫忙檢查 workflow、load replay、support mapping、report parsing 有沒有歪掉，但不能單獨當 validation truth。
- Current caution:
  - 報告自己明確寫 `INFO ONLY`。
  - support reaction 與 main tip deflection 差距仍大，不能被過度宣稱為 already-close。
  - 後續若要做真正 validation，應補一個同幾何 / 同 BC / 同 load ownership 的 external benchmark case。

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

### 5. `output/blackcat_004/hifi_support_reaction_rerun_20260418`

- Paths:
  - `/Volumes/Samsung SSD/hpa-mdo/output/blackcat_004/hifi_support_reaction_rerun_20260418/structural_check.md`
  - `/Volumes/Samsung SSD/hpa-mdo/output/blackcat_004/hifi_support_reaction_rerun_20260418/structural_check.json`
  - `/Volumes/Samsung SSD/hpa-mdo/output/blackcat_004/hifi_support_reaction_rerun_20260418/spar_jig_shape.mesh_diagnostics.json`
  - `src/hpa_mdo/hifi/structural_check.py`
- Why it matters:
  - 本機 Mac route 是未來最值得持續投資的 validation path。
  - 最新 code 已支援 `structural_check.json`、`mesh_diagnostics` sidecar、`comparability`、`issue_category` 與更明確的 solver diagnostics。
  - STEP meshing 現在會先經過 OCC healing wrapper（`HealShapes + Coherence`），而且仍維持最多一次 coarse retry，不會無上限重試。
  - `ROOT/TIP/WIRE` 現在已直接由 spanwise matching 寫成 NSET，不再依賴舊的 `(x,y,z)` 最近點假設。
  - analysis deck 現在也會去除完全重複、只差方向的 shell facets，並補上 shell normals consistency 與極低品質 sliver shell 過濾。
  - `spar_data.csv` 現在若帶有 `Main_X/Z`、`Rear_X/Z`，會做 spatial main/rear load replay，而不是把 `Main_FZ_N + Rear_FZ_N` 壓成單一節點。
  - 若 `hifi_structural_check` 指定了 summary / crossval report，現在會優先選同一個 evidence root 旁邊的 `spar_data.csv`，避免拿 archived summary 去比 current output 的 load table。
  - 若 `load_model.source_kind = spar_csv`，wire support 也會優先對齊到同一份 CSV 的 `Main_X_m / Main_Z_m` 幾何位置，而不是盲目沿用 mesh 內建 `WIRE_n` NSET。
  - 若 target 附近有幾乎等距的 shell nodes，wire support 現在會收成最多 2 個近鄰 nodes 的 local support cluster，而不是單點約束。
  - static deck 現在也會額外輸出 `HPA_SUPPORT_ALL / ROOT / WIRE` 的 RF totals 到 `.dat`，讓 `structural_check` 能直接做 support reaction compare。
  - 這次 fresh representative healed run 已把 inspection reference 對齊到：
    `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`
- Current caution:
  - fresh run 仍是 `WARN`，而且 `overall_comparability` 只有 `LIMITED`。
  - `ROOT clamp nodes=35`、`wire U3 supports=2` 已合理化，代表 boundary contract 這一層仍維持乾淨。
  - OCC healing 後，mesh sidecar 已不再出現：
    - `overlapping_boundary_mesh`
    - `no_elements_in_volume`
    - `duplicate_boundary_facets`
  - 經過 shell normals consistency + sliver filter，再加上 spatial main/rear load replay 與 summary-root 對齊後：
    - `static` 已可完成並回傳 `|uz_tip| = 2.55449 m`
    - `buckle` 已可完成並回傳 `lambda_1 = 85125.46`
    - `support_reactions.actual_total_fz_n = 817.805246222`
    - `static comparability = COMPARABLE`
    - `support_reactions.comparability = COMPARABLE`
    - `buckle comparability = LIMITED`
  - 最新 mesh 維度診斷也已明確指出：
    - `analysis_reality = shell_plus_beam`
    - `element_family_counts = beam 2439 / shell 12918 / solid 0`
    - `has_volume_elements = false`
  - total support reaction 相對 reference `817.782 N` 的差距只剩約 `0.00284%`，代表 load-balance / total-support closure 已很乾淨。
  - 但 static tip deflection 相對 inspection reference 仍差約 `6.72%`，所以目前最該修的是 shell-truth / section / support completeness 的剩餘差距，而不是再回頭重查 named-point / boundary contract。
  - 這些數字目前能證明的是「Mac route 已可當 local spot-check」，還不能證明「Mac route 已被 external truth 驗證」。

## Practical Recommendation

- 如果今天只想先做 workflow inspection，先選 `blackcat_004_dual_beam_production_check`。
- 如果今天要做真正 validation，不要把 `blackcat_004_dual_beam_production_check` 直接當 external truth；先補一個 apples-to-apples external benchmark case。
- 如果要看 design ordering / sensitivity，再加上 `dual_spar_spotcheck_neighbors`。
- 如果要做 repo 歷史脈絡或風險對照，再保留 `dual_spar_spotcheck` baseline。
- Mac `structural_check` 現在已經有 fresh representative run，而且 boundary/NSET contract、shell normal consistency、sliver filtering 都已補上；它目前證明的是「solver 直接 fail 這關已經跨過」，但還沒有證明「數值結果已經足夠接近 reference」。
