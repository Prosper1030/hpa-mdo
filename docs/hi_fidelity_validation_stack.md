# 高保真驗證層現況與路線圖（Apple Silicon Mac mini）

> **狀態**：**部分實作，現階段定位為 local structural spot-check**。repo 內已經有 `Gmsh -> CalculiX -> report` 與 `ParaView` / `ASWING` glue code，但它目前還不是最終真值，也不應該拿來直接背書 discrete layup 或完整 aeroelastic sign-off。
> **重要澄清**：`crossval_report.txt` 在這條線上最多只能當 **internal inspection reference / export contract**，不是獨立高保真真值；不能把「更接近 internal crossval」直接寫成「完成 validation」。
> **這份文件要回答的問題**：現在高保真層實際做到哪裡、能拿來做什麼、不能拿來做什麼、下一步怎麼驗。

## 1. 角色定位

MDO 內圈仍然使用中保真度的結構與氣動模型做快速設計收斂。高保真層的近期角色不是取代它，而是：

- 在同一台 Apple Silicon Mac 上做本機 structural spot-check
- 幫忙抓幾何、支撐、載入映射是否明顯翻車
- 幫忙判斷 finalist / suspicious design 是否有 model-form risk

目前不應把它當成：

- 每次設計都必跑的主流程
- 已取代 Windows / ANSYS 的完整最終真值
- 已驗證 discrete CFRP / layup 的複材真值
- 已完成的非線性 aeroelastic sign-off 鏈

## 2. repo 目前做到哪裡

### A. 已存在的 code path

| 層 | repo 內模組 / script | 目前狀態 | 角色 |
|---|---|---|---|
| STEP -> mesh | `src/hpa_mdo/hifi/gmsh_runner.py`, `scripts/hifi_mesh_step.py` | 已實作 | 將 STEP 轉成 CalculiX 可用的 `.inp`，並補上 `ROOT` / `TIP` / `WIRE_n` 類命名節點集；目前 `ROOT` 走 spanwise plane、`TIP/WIRE` 走 spanwise station matching |
| CalculiX static / buckle | `src/hpa_mdo/hifi/calculix_runner.py`, `scripts/hifi_structural_check.py`, `scripts/hifi_buckle_check.py` | 已實作 | 生成 standalone deck，跑 static 與 `*BUCKLE`，輸出 `.frd` / `.dat` / report |
| 結構驗證總控 | `src/hpa_mdo/hifi/structural_check.py`, `scripts/hifi_structural_check.py` | 已實作 | 串起 summary -> STEP -> mesh -> static -> buckle -> Markdown 報告 |
| ParaView | `src/hpa_mdo/hifi/paraview_state.py`, `scripts/hifi_open_paraview.py` | 已實作 | 產生 `pvpython` 視覺化腳本 |
| ASWING runner | `src/hpa_mdo/hifi/aswing_runner.py`, `scripts/hifi_validate_aswing.py` | 已實作 glue | 可驅動 ASWING batch mode，但是否能跑取決於本機有沒有 `aswing` binary |
| CFD / SU2 | `src/hpa_mdo/aero/origin_su2.py`, `src/hpa_mdo/aero/origin_gmsh_mesh.py`, `scripts/origin_aero_sweep.py` | 已有 runnable baseline | 可做 origin geometry 的單一 case / alpha sweep baseline 與結果讀回；目前仍不是高品質 drag 真值，mesh study 與 near-wall quality 尚待補強 |

### B. 目前最接近可用的部分

最接近可用的是：

`summary -> jig STEP -> Gmsh -> CalculiX static/buckle -> Markdown report + structural_check.json + mesh_diagnostics sidecar`

正式入口：

```bash
python scripts/hifi_structural_check.py --config configs/blackcat_004.yaml
```

這條線已經不只是藍圖，而是實際可執行的 structural check driver。

## 3. 目前的信任邊界

現在這條 Mac 高保真路線，最適合被理解成：

`幾何 / 支撐 / 載入映射 sanity check + 結構級 spot-check`

而不是：

`完整 layup-aware composite truth model`

### 目前簡化在哪裡

- **材料模型仍是簡化版**
  - `structural_check.py` 目前從 `data/materials.yaml` 取的是 `E / nu / rho`
  - 也就是說，它現在不是 layup-aware section，也不是完整複材疊層真值
- **載入模型已部分升級，但仍不是完整真值**
  - 優先從 `ansys/spar_data.csv` 取展向 `Main_FZ_N / Rear_FZ_N`
  - 若 CSV 有 `Main_X/Z`、`Rear_X/Z`，現在會分 main / rear 各自映射到 mesh
  - 但目前還不是完整 torque / twist / aeroelastic load ownership truth
- **支撐模型仍是 spot-check 型**
  - 目前以 `ROOT clamp + wire U3 supports` 為主
  - 這是有效的結構級對照，但仍不是完整製造 / 接頭 / 柔性邊界真值

### 所以現在能拿來判斷什麼

- tip deflection 有沒有完全錯位
- `Max |UZ|` 是否明顯翻盤
- support reaction / total reaction 是否對得上
- mass / deck 組裝 / mesh 邏輯是否基本一致
- mesh、BC、load mapping 問題是不是在一開始就爆掉

### 目前不能過度宣稱什麼

- 不能拿它直接背書 discrete layup 結果
- 不能拿它直接背書複材 torsion-coupled behavior
- 不能拿它直接當完整 aeroelastic sign-off
- 不能因為它出現數字就宣稱已取代 ANSYS/APDL

## 4. 目前已知的驗證證據

### A. 歷史 ANSYS/APDL 與 internal crossval 都有價值，但角色不同，不能混成真值

這裡要明確分三種東西：

- **solver verification / usage semantics**
  - 例如 keyword 有沒有用對、`RF` 到底代表什麼、shell normals / node ordering 是否符合 solver 假設。
- **inspection reference / export contract**
  - 例如 repo 內的 `crossval_report.txt`，它描述的是 internal mainline 預期要輸出的指標與封裝格式。
- **validation truth**
  - 真正 apples-to-apples 的外部 benchmark，例如同幾何、同 BC、同 load ownership 的 APDL/ANSYS case，或實驗量測。

`crossval_report.txt` 可以幫你檢查：

- export / compare contract 有沒有歪掉
- load replay / support mapping / report parsing 有沒有明顯翻車

但它**不能單獨證明**：

- Mac CalculiX 已經接近外部高保真真值
- dual-beam production 的物理模型已被 validation 背書
- 目前 shell-plus-beam spot-check 已可升格成最終 sign-off

所以目前 repo 與 `SyncFile` 裡可讀到的證據，比較適合寫成「inspection / engineering judgment evidence」，而不是「已完成 validation」：

- `dual_spar` baseline spot-check：
  - tip deflection 差 `14.14%`
  - `Max |UZ|` 差 `35.64%`
  - support reaction / mass 很接近
  - 結論是 `MODEL-FORM RISK`
- `dual_beam_production` 對同組 ANSYS surrogate：
  - main tip deflection 差 `19.21%`
  - total support reaction 差 `11.34%`
  - 報告定位是 `INFO ONLY`

這代表：

- ANSYS/APDL 路線仍然值得保留作 evidence
- 但它目前還不足以支持「repo 現在已經和 APDL 很 close，所以可直接鎖死 benchmark」

### B. Mac structural check 已有正式 compare/diagnostic schema，且 fresh representative run 仍指向 mesh-quality blocker

`Track C` 與後續 mesh-diagnostics 補強完成後，`structural_check` code path 已可輸出：

- Markdown report
- `structural_check.json`
- `spar_jig_shape.mesh_diagnostics.json`
- `comparability`
- `issue_category`
- `analysis_reality`
- `element_family_counts`
- `has_volume_elements`
- solver / diagnostics 摘要
- Gmsh upstream mesh root-cause hints（例如 `overlapping_boundary_mesh`、`no_elements_in_volume`、`duplicate_shell_facets`）

目前已補上一份 fresh representative run，inspection reference 對齊到：

- `/Volumes/Samsung SSD/SyncFile/blackcat_004_dual_beam_production_check/ansys/crossval_report.txt`

代表性 artifact：

- `output/blackcat_004/hifi_dual_beam_production_syncfile_reference_nsetfix/structural_check.md`
- `output/blackcat_004/hifi_dual_beam_production_syncfile_reference_nsetfix/structural_check.json`
- `output/blackcat_004/hifi_dual_beam_production_dedupcheck/structural_check.md`
- `output/blackcat_004/hifi_dual_beam_production_dedupcheck/structural_check.json`
- `output/blackcat_004/hifi_dual_beam_production_stepdiag/structural_check.md`
- `output/blackcat_004/hifi_dual_beam_production_stepdiag/structural_check.json`
- `output/blackcat_004/hifi_dual_beam_production_stepdiag/spar_jig_shape.mesh_diagnostics.json`
- `output/blackcat_004/hifi_heal_probe/spar_jig_shape.mesh_diagnostics.json`
- `output/blackcat_004/hifi_heal_structcheck/structural_check.json`
- `output/blackcat_004/hifi_heal_rerun_filtered_20260417/structural_check.json`

該案例目前是：

- `Overall status: WARN`
- `Overall comparability: NOT_COMPARABLE`
- `ROOT/TIP/WIRE` 已可直接從 mesh 產生 NSET
- `ROOT clamp nodes=28; wire U3 supports=1`
- duplicate shell facets 去重後，`opposite_normals` 已從 `4762` 降到 `3370`
- static / buckle 仍分類成 `mesh_quality`
- CalculiX static 發生大量 `opposite normals are defined`
- 並且出現 `nonpositive jacobian`
- 直接從 STEP 開始跑的代表性案例，現在會把 Gmsh upstream 問題寫進 `mesh_diagnostics`：
  - `overlapping_boundary_mesh x1`
  - `no_elements_in_volume x1`
  - `duplicate_boundary_facets x2`
  - `invalid_surface_elements x38`
  - `equivalent_triangles x2128`
  - `duplicate_shell_facets x599`
- 在此之後，`gmsh_runner` 又加入了 OpenCASCADE healing wrapper（`HealShapes + Coherence`）與 bounded coarse fallback：
  - 最新 healed mesh sidecar 已降成：
    - `invalid_surface_elements x12`
    - `equivalent_triangles x340`
    - `duplicate_shell_facets x259`
  - 先前的 `overlapping_boundary_mesh x1`
  - `no_elements_in_volume x1`
  - `duplicate_boundary_facets x2`
    已不再出現
  - healed mesh 重新進 CalculiX 後，solver diagnostics 也從
    `opposite_normals x3370 / nonpositive_jacobian x34`
    降到
    `opposite_normals x732 / nonpositive_jacobian x10`
  - `ROOT/TIP/WIRE_1` 在 healed coarse mesh 上仍可維持
  - 直接對目前 healed mesh 做維度診斷時，分類結果是：
    - `analysis_reality = shell_plus_beam`
    - `element_family_counts = beam 2439 / shell 12918 / solid 0`
    - `has_volume_elements = false`
  - 也就是說，這條 Mac hi-fi 目前更接近 shell-surface truth with beam members，不是乾淨的 solid-volume benchmark
  - 在此之後，analysis deck 又補上兩層保守處理：
    - shell normals consistency pass
    - 極低品質 sliver shell 過濾（目前門檻 `quality < 1.5e-3`，fresh representative case 會濾掉 20 個最差 shell）
  - 最新 fresh rerun 已經不再停在 `mesh_quality fail`：
    - `static` 進到 `COMPARABLE`
    - `buckle` 可完成並回傳 `lambda_1`
    - `overall_comparability` 升到 `LIMITED`
  - 接著又補上 `spar_data.csv` 的 spatial main/rear load replay：
    - 有 `Main_X/Z`、`Rear_X/Z` 時，不再把 `Main_FZ_N + Rear_FZ_N` 壓成單一節點 replay
    - 而是依 main / rear 各自的展向位置與幾何座標分開映射到 mesh
    - fresh representative rerun：`output/blackcat_004/hifi_spatial_load_rerun_20260417/structural_check.json`
    - `static` 仍是 `COMPARABLE`
    - `overall_comparability` 仍是 `LIMITED`
    - 但 static tip deflection 已從 `4.7992 m` 明顯收斂到 `3.16127 m`
    - 相對 reference `2.39372 m` 的差距也從約 `100.49%` 降到 `32.07%`
  - 接著又補上 summary-root 對齊：
    - 當 `hifi_structural_check` 明確指定某份 `summary / crossval_report` 時，現在會優先吃同一個 evidence root 旁邊的 `spar_data.csv`
    - 不再用 archived summary 去比 current output root 的 load table
    - fresh representative rerun：`output/blackcat_004/hifi_summary_aligned_rerun_20260418/structural_check.json`
    - `load_model.source_path` 已對齊到
      `output/_archive_pre_2026_04_15/blackcat_004_dual_beam_production_check/ansys/spar_data.csv`
    - static tip deflection 進一步收斂到 `3.02214 m`
    - 相對 reference `2.39372 m` 的差距也再從 `32.07%` 降到 `26.25%`
  - 接著又補上 wire-support 與同一份 `spar_data.csv` 的 main spar 幾何對齊：
    - 若 `load_model.source_kind = spar_csv`，現在 wire support 會優先用同一份 CSV 的 `Main_X_m / Main_Z_m` 幾何位置挑 support node
    - 不再盲目沿用 mesh 內建的 `WIRE_n` NSET
    - fresh representative rerun：`output/blackcat_004/hifi_wire_support_aligned_rerun_20260418/structural_check.json`
    - `static comparability` 仍是 `COMPARABLE`
    - `overall_comparability` 仍是 `LIMITED`
    - static tip deflection 再從 `3.02214 m` 收斂到 `2.96129 m`
    - 相對 reference `2.39372 m` 的差距也再從 `26.25%` 降到 `23.71%`
    - 這代表 wire-support contract 仍有工程影響，但剩餘 blocker 已更集中在 shell / section / support completeness，而不是 evidence-root 或 generic wire NSET 選錯
  - 接著又補上 wire-support 的 local cluster 對齊：
    - 若 `spar_csv` main-spar target 附近有幾乎等距的 shell nodes，現在會收成一個很小的 local support patch，而不是只夾單一 node
    - 目前預設最多吃 2 個近鄰 support nodes，避免過度擴張成大面積約束
    - fresh representative rerun：`output/blackcat_004/hifi_wire_support_cluster_rerun_20260418/structural_check.json`
    - `static comparability` 仍是 `COMPARABLE`
    - `overall_comparability` 仍是 `LIMITED`
    - support description 已變成 `ROOT clamp nodes=35; wire U3 supports=2`
    - static tip deflection 再從 `2.96129 m` 收斂到 `2.55449 m`
    - 相對 reference `2.39372 m` 的差距也再從 `23.71%` 降到 `6.72%`
    - 這代表 current Mac hi-fi 的主要 mismatch 已不再是 generic wire support mapping，而更像 shell / section / support completeness 的剩餘 model-form 差距
  - 接著又補上 support reaction compare：
    - static deck 現在會額外輸出 `HPA_SUPPORT_ALL / ROOT / WIRE` 的 RF totals 到 `.dat`
    - `structural_check.json` / Markdown report 也會直接帶出 `support_reactions`
    - fresh representative rerun：`output/blackcat_004/hifi_support_reaction_rerun_20260418/structural_check.json`
    - `support_reactions.comparability = COMPARABLE`
    - total support reaction `|Fz|` 已對齊到 `817.805 N`
    - 相對 reference `817.782 N` 的差距只剩約 `0.00284%`
    - 這代表 current Mac hi-fi 的 load-balance / total-support closure 已經很乾淨；剩下更像 tip deflection / shell-section model-form 差距，而不是整體受力平衡還沒對齊

另外，直接對同一份 `spar_jig_shape.step` 做 Gmsh probe 時，可以明確看到：

- `-3` volume meshing 會在 3D 階段報 `Invalid boundary mesh (overlapping facets)`
- 並伴隨 `No elements in volume`
- 改成 `-2` surface-first meshing 雖能避開 volume 階段報錯，但仍無法單獨解掉 CalculiX 的 `mesh_quality`

所以目前最大問題比較像：

- STEP / Gmsh surface 仍殘留的 invalid facets / equivalent triangles / shell duplication
- shell mesh normals / Jacobian 仍未完全收斂
- 目前代表性 healed mesh 本身也明確不是 solid-volume mesh
- 即使加上 shell-orientation + sliver filter，再補上 spatial main/rear load replay、summary-root 對齊、wire-support local cluster 與 support reaction compare 後，static tip deflection 雖已明顯收斂到約 `6.72%`，但 shell / section / support completeness 與 reference 仍未完全一致

而不是：

- root-plane boundary 只抓到單點
- named-point / NSET mapping 本身先失敗
- analysis deck 裡還保留大量完全重複的 shell facets
- repo 完全沒有高保真 code path

換句話說，目前結論是：

- **能力層**：Mac structural spot-check 的 compare/diagnostic schema 已存在
- **可診斷性層**：report / JSON 已能同時講出 CalculiX failure 與 Gmsh upstream root cause
- **contract 收斂層**：`spar_data.csv` 現在已能做 spatial main/rear load replay，而且 summary / load evidence root 已可對齊，代表最粗的雙梁載重扁平化與跨 root 對照問題都先被修掉
- **support 對齊層**：wire support 現在也能優先對齊到同一份 `spar_data.csv` 的 main spar 幾何位置，代表 generic `WIRE_n` NSET 帶來的次級誤差也開始被壓掉
- **local patch 支撐層**：wire support 現在可在 main-spar target 附近收成小範圍 cluster，代表單點約束造成的次級柔化也開始被壓掉
- **reaction 收斂層**：support reaction compare 現在也已正式進到報告與 JSON，代表 total support closure 已可直接驗證，不再只能靠 tip deflection 側寫
- **benchmark basket 層**：fresh representative run 已經補齊，但它仍不能升格成正式 candidate，因為 blocker 已轉成 shell / section / support / load completeness，而不是 mesh fail 本身

## 5. benchmark policy：先保持開放，不先釘死

近期的 benchmark policy 應該是：

- **不把某一份舊 APDL case 直接升格成唯一 sign-off benchmark**
- 歷史案例保留為 evidence
- 當前優先找一份**新鮮、可比、定義清楚**的 dual-beam / jig-oriented case 做本機 structural check 對照

比較好的做法是維持一個 `benchmark basket`：

- 歷史 dual-spar / dual-beam ANSYS/APDL case
- 最新的可比 dual-beam production / inverse-design case
- 未來如果 Mac high-fidelity 成熟，再把本機 structural check case 加進來

如果要把這件事交給另一個 AI agent 先整理，請從 [task_packs/benchmark_basket/README.md](task_packs/benchmark_basket/README.md) 開始。
目前已整理出的候選清單請看 [task_packs/benchmark_basket/benchmark_candidates.md](task_packs/benchmark_basket/benchmark_candidates.md)。

這樣做的好處是：

- 不會被一份已經過一段時間的舊 case 綁死
- 可以隨主線演進更新驗證目標
- 更符合目前主線已從 parity 轉向 inverse-design / jig artifacts 的事實

## 5.5 沒有商業軟體、沒有一堆 AI agent 時，以前的人到底怎麼做

以前的工程師和研究者，通常不是靠「一次找到完美真值」來工作，而是靠一個分層的驗證習慣：

### A. 先做 solver verification，不先談完整 validation

先確認的是：

- keyword / element / output semantics 有沒有用對
- 官方 manual 的假設有沒有踩錯
- 官方 verification examples 能不能跑通

這一步在 open-source solver 裡很正常。像 CalculiX 自己就附了一整套 verification examples，Code_Aster 也有專門的 validation / `TEST_RESU` 機制。這些不是在證明你的飛機就是真的，而是在證明「你至少沒有把 solver 用錯」。

### B. 再做 canonical benchmark，不必一開始就找商業軟體

很多人會先拿：

- 解析解可得的梁、板、殼問題
- 教科書 / 官方 benchmark
- mesh convergence 會收斂的簡化問題

來確認：

- 量級對不對
- 收斂趨勢對不對
- 主要 response 對 BC / mesh / load 定義是否合理

這一步的目標是建立「這套工具鏈有沒有基本可信度」，不是直接證明最終複雜模型全對。

### C. 再做 cross-code comparison 或實驗對照

如果有另一套 solver，就做 apples-to-apples compare。
如果沒有商業軟體，很多研究工作也會：

- 和別人的公開 benchmark 比
- 和文獻中的 reference case 比
- 和自己做得出的簡單試件 / 子結構量測比

真正重要的是 case 要定義清楚，同幾何、同 BC、同 load ownership，而不是 solver 名字一定要是商業品牌。

### D. 最後用 fitness-for-purpose 來收斂，而不是追求神聖真值

很多時候工程上真正需要的是：

- 這個模型能不能正確判斷趨勢
- 能不能抓到明顯錯誤
- 能不能當 screening / spot-check / ranking risk tool

而不是一開始就宣稱它是 final truth。

所以對這個 repo 來說，現在更健康的說法應該是：

- Mac CalculiX 這條線目前已經開始具備 **solver verification + local spot-check** 的價值
- 但還沒有完成 **external validation truth**

## 6. 推薦的驗證階梯

### Stage 1：先把本機 structural check 跑穩

目標：

- 同一個代表性案例可以穩定完成 `mesh -> static -> buckle -> report`
- 清楚知道目前比對的是 inspection reference 還是 external truth

先看四個基本量：

- tip deflection
- `Max |UZ|`
- support reaction
- mass

### Stage 2：先把它變成可信 spot-check

當 Stage 1 穩定後，再要求：

- 能清楚區分 mesh 問題、BC 問題、load mapping 問題
- 代表性 case 的結果不再充滿 Jacobian / normals 類硬錯誤
- 報告能穩定告訴你「這個 case 是可比」還是「這個 case 目前不可信」
- 不把 internal crossval 的靠近程度誤寫成 validation 完成度

### Stage 3：再擴大 load / geometry contract

下一步才值得補：

- 更完整的 torque / twist / aeroelastic load contract
- 更明確的 jig vs loaded geometry 選擇規則
- 更一致的 benchmark case ownership

### Stage 4：最後才談 layup-aware truth

真正要往最終真值推時，才值得再往下做：

- layup-aware section / composite property recovery
- 更完整的 CFRP / shell / hotspot 驗證分層
- 更接近最終真值的局部驗證模型

## 7. 推薦的工作順序

如果現在要投資高保真這條線，最值得的順序是：

1. 先把 `Gmsh -> CalculiX -> report` 跑穩
2. 用 manual + verification examples + canonical beam/shell benchmark 確認 solver usage 沒有歪
3. 再選一個新鮮且可比的 dual-beam / inverse-design external benchmark case
4. 然後才對齊 tip deflection / `Max |UZ|` / support reaction / mass
5. 在 external benchmark 沒釘清前，先把它定位成 **non-gating local structural spot-check**
6. 之後才考慮更完整的 load contract 或複材真值升級

不建議的順序是：

- 還沒跑穩 structural check 就先追求 full aeroelastic hi-fi
- 還沒解決 mesh / Jacobian 問題就先把結果拿來背書 layup
- 還沒選好 external benchmark case 就先把文件寫成已完成驗證
- 拿 internal crossval report 當 validation truth 持續校正

## 8. 工具鏈與資料流

### 工具鏈

| 層 | 工具 | 角色 | 近期定位 |
|---|---|---|---|
| 幾何 / 網格 | **Gmsh** | STEP -> `.inp` | 近期主力 |
| 結構 solver | **CalculiX (ccx)** | static / buckle | 近期主力 |
| 後處理 | **ParaView** | `.frd` 視覺化 | 輔助 |
| 非線性氣動彈 | **ASWING** | trim / nonlinear aeroelastic | glue 已有，是否可用取決於 binary |
| CFD | **SU2** | RANS / Euler CFD | 長期藍圖，不是近期 blocker |

### 資料流

```text
summary / selected design
-> jig-oriented STEP
-> Gmsh mesh (.inp)
-> CalculiX static / buckle
-> Markdown report + FRD + ParaView script
```

### 呼叫時機

高保真層**不**進最佳化內圈，只在驗證時由使用者或獨立 script 觸發：

```bash
python scripts/hifi_structural_check.py --config configs/blackcat_004.yaml
```

如果本機沒有對應 binary，runner 應回報 `INFO` / `WARN`，而不是把主流程炸掉。

## 9. 參考資料清單

### P0 — 實作與 debug 前一定要讀

| 主題 | 來源 | 用途 |
|------|------|------|
| CalculiX User's Manual v2.22+ | [官方 PDF](http://www.dhondt.de/) | `.inp` 語法、`*STATIC` / `*BUCKLE` / `*BOUNDARY` / `*CLOAD` |
| CalculiX verification examples | [官方文件](https://web.mit.edu/calculix_v2.7/CalculiX/ccx_2.7/doc/ccx/node331.html) | 確認安裝、keyword 使用方式與 element/solver feature 是否如預期 |
| Gmsh Reference Manual | [gmsh.info/doc](https://gmsh.info/doc/texinfo/gmsh.html) | STEP meshing、Physical Groups、INP 匯出 |
| ParaView Python Scripting Guide | [docs.paraview.org](https://docs.paraview.org/en/latest/ReferenceManual/pythonAndBatchPvpythonAndPvbatch.html) | `pvpython` 視覺化腳本 |

### P1 — benchmark 對照與升級時再讀

| 主題 | 來源 | 用途 |
|------|------|------|
| CalculiX regression / tutorial cases | [dhondt.de](http://www.dhondt.de/) | golden compare 與 deck 格式 sanity check |
| Code_Aster `TEST_RESU` / validation process | [官方文件](https://code-aster.org/doc/default/en/man_u/u4/u4.92.01.pdf) | 參考 open-source FEA 社群如何把 verification、non-regression 與 validation 分層 |
| NASA SP-8007 | NASA TRS | 薄殼挫曲背景與 `*BUCKLE` 對照 |
| Daedalus / HPA flight-test data | AIAA / MIT papers | 柔性翼全球變形 benchmark 背景 |

## 10. 非目標

- 不取代 MDO 內圈的中保真 solver
- 不把本機 structural check 說成複材最終真值
- 不讓高保真層成熟與否決定主線是否停擺
- 不因為有 runner 就宣稱所有高保真驗證已完成
