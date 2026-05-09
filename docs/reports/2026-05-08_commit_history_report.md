# HPA-MDO Commit History Report

> 產出日期：2026-05-08；Phase J 後續補強更新：2026-05-09
> 目的：用 git commit history 重建目前飛機設計脈絡，供日本側機體設計概念文件使用。
> 主要依據：目前 `HEAD/main` 的 commit subject 全量索引、現行 truth 文件、最新 candidate / FEM / Go Mode 輸出。
> 注意：本報告不是所有舊 README 或舊研究文件的合併摘要。當舊文件與現行主線衝突時，以 `CURRENT_MAINLINE.md`、Phase J pipeline、最新 candidate package 與 commit history 為準。
> 2026-05-09 補記：索引檔仍是 2026-05-08 原始快照；本報告正文另外補上 `0a754030..5580f35f` 的 Phase J 後續結構宣稱 / guardrail 工作。

## 0. 產出檔案

本次整理新增三種資料層：

- `docs/reports/2026-05-08_commit_history_index_main.tsv`
  - 目前 `HEAD/main` 可到達的 1090 筆 commit。
  - 欄位包含 `index`、`hash`、`short_hash`、`date`、`author`、`prefix`、`category_hint`、`subject`。
- `docs/reports/2026-05-08_commit_history_index_all_refs.tsv`
  - `git log --all` 可看到的 1217 筆 unique commit。
  - 另外標示 `reachable_from_head_main`，避免把非主線或舊分支誤當成目前狀態。
- `docs/reports/2026-05-08_commit_history_stats.csv`
  - prefix、日期、初步分類統計。

本報告的工程敘事以 `HEAD/main` 的 1090 筆 commit 為主。`all_refs` 只作為「確實還有其他歷史/分支 commit」的保留索引，不直接拿來定義目前機體狀態。

2026-05-09 補記沒有重新產生 TSV / CSV 索引；它只把 Phase J 之後的 99 筆主線 commit
作為 addendum 納入本文工程判讀，避免 README / CURRENT_MAINLINE 繼續停在舊主線敘事。

## 1. Raw Commit Facts

### 1.1 範圍

- 原始 `HEAD/main` commit 數：1090
- 2026-05-09 補記時 `HEAD/main` commit 數：1189
- `git log --all` unique commit 數：1217
- 原始 `HEAD/main` 時間範圍：2026-04-06 14:11:48 +0800 到 2026-05-08 22:24:55 +0800
- 原始最新 `HEAD/main` commit：`0a754030` - `fix: 修正 candidate shell buckling 載重步驟`
- 2026-05-09 補記最新 commit：`5580f35f` - `fix: 要求 rib bracing 來源可追溯`
- 第一筆 commit：`70f8255e` - `Initial commit`

### 1.2 Prefix 統計

`HEAD/main` 的 commit subject 顯示，這個 repo 不是只有文件堆疊，而是很密集地把功能、修正、測試、報告一起推進：

| prefix | count | 判讀 |
|---|---:|---|
| `feat` | 492 | 大量新增功能或 pipeline 能力，表示設計流程仍在快速演化 |
| `fix` | 239 | 很多修正都針對物理/資料契約/工具可靠性，不只是語法 bug |
| `docs` | 207 | 文件常常是任務成果本體，尤其是驗證政策、handoff、工程判讀 |
| `test` | 65 | 測試主要落在 parser、load mapper、inverse design、FEM、candidate package |
| `refactor` | 19 | 多數是早期工程化與 API/架構整理 |
| 其他 | 68 | 包含 build、ci、perf、merge、revert、具 scope 的 conventional commit |

### 1.3 日期密度

最密集的幾天代表主線大幅轉向或建立大量工程基礎：

| date | commits | 主要事件 |
|---|---:|---|
| 2026-05-01 | 131 | mesh-native main wing / SU2 支線大量建立與凍結 |
| 2026-04-22 | 84 | Birdman upstream concept 與 shell/mesh route 大幅推進 |
| 2026-04-08 | 82 | repo 工程化、OpenMDAO/安全/屈曲/LoadMapper 早期修正 |
| 2026-04-23 | 70 | shell_v4 / high-fidelity mesh validation route |
| 2026-04-17 | 68 | validation framing、CURRENT_MAINLINE、CFRP/discrete layup、parallel task pack |
| 2026-04-30 | 67 | main-wing route productization、VSPAERO panel reference、mesh-native readiness |
| 2026-05-08 | 38 | Phase 14 FEM/APDL、Go Mode candidate、Phase 15/16/17 structural checks |

## 2. How To Read This History

這份 repo 的 commit subject 大多可信，因為它們通常是一個任務一個 commit。不過仍有三個解讀原則：

1. `feat` 不等於工程已驗證。很多 `feat` 是把 route、diagnostic、report、candidate contract 接起來，必須再看後面的 `test`、`fix`、`docs: trust policy`。
2. `docs` 不一定只是輔助說明。這個 repo 裡很多工程判斷是以報告、handoff、policy 文件作為正式產物。
3. `README.md` 和 `CURRENT_MAINLINE.md` 必須跟著 commit history 回寫更新；若它們與 Phase J pipeline 或最新 candidate / FEM 輸出衝突，先以 commit-derived evidence 修正主文件，而不是沿用舊敘事。

## 3. Executive Bottom Line

目前這個專案已經不是「拿一台既有 Black Cat 004 幾何，做 spar sizing」的單純結構最佳化工具。commit history 顯示它逐步變成一條更完整的機體設計流程：

```text
Mission contract
-> Fourier-AVL calibration
-> Fourier spanload candidate generation
-> smooth production geometry realization
-> AVL realization check
-> structure-budgeted loaded-Z search
-> AVL recheck on realizable loaded shape
-> Tier2 full-alpha airfoil selection
-> aero-structure closure
-> FEM/APDL / shell buckling / load-factor checks
```

重新設計飛機的理由不是「想換外型」而已，而是目前證據顯示：

- 舊的 airfoil-first 或 geometry-first 流程會把 local `Cl/Re`、spanload、loaded shape、結構可行性分開看，容易得到漂亮但不可製造/不可實現的結果。
- 現行 6-7 deg 低 beam-line Z interpretation，在目前 beam-line contract 與 selected-airfoil spanload 下沒有通過 mass + ground-clearance screening。
- 目前可推進的是 `current_avl_compromise_conservative_closed` 這個 screening candidate，不是 final production truth。
- 最新 FEM / CalculiX / shell buckling 工作已把很多工具錯配修掉，Phase J 後續也新增一系列 structural claim-boundary / engineering guardrail；但 candidate 仍停在「internal screening + candidate-relevant equivalent-physics validation」層級，還不到 composite/root-joint/rib-joint/wire-hardware/flight sign-off。
- Birdman upstream concept 線的舊 real Julia/XFOIL run 沒有找到可完成 42.195 km 的完全可行解，最佳診斷點航程約 16.1 km，因此新的機體概念不能只沿用舊假設，必須重新整理 mission、span cap、wing area、airfoil、prop、wire-braced structure。

## 4. Development Phases From Commit History

### Phase A - 2026-04-06 to 2026-04-08: OpenMDAO Dual-Spar Foundation

代表 commit：

- `0bef99ac` - `v2.0: OpenMDAO SpatialBeam FEM, dual-spar optimization, full pipeline`
- `15e37914` - `v2.1: 外徑設計變數、視覺化修復、繁體中文文件`
- `045caca5` - `fix: P0 修正 - 移除硬編碼、FSI修復、輸入驗證、動態段數`
- `ea1ed047` / `7ad08f2d` - buckling component and OpenMDAO wiring
- `e6acd355` / `35b0517` 類似主題 - scipy path enforcing buckling constraints

這個階段建立了最初的工程骨架：

- 6-DOF Timoshenko / SpatialBeam OpenMDAO FEM
- dual-spar equivalent beam
- tube thickness / OD design variables
- VSPAero / XFLR5 parser
- load mapper
- material database
- API / MCP server
- ANSYS/NASTRAN/CSV export
- CI、pytest、logging、structured error code

工程意義：

最早的 repo 已經不是純概念文件，而是一個會跑的 structural sizing / aero-load mapping framework。但早期也很快暴露出物理路徑風險，例如 load factor、buckling、twist KS aggregation、LoadMapper 超出範圍時 lift 膨脹等問題。這些修正說明：repo 從第一週就不是只在追軟體乾淨，而是在修會直接改變結構結果的工程錯誤。

為什麼進入下一階段：

光有 FEM + optimizer 不夠。人力飛機的 loaded shape、wire support、aero load ownership、manufacturing constraints 會互相改變設計，因此需要把「外形」、「載荷」、「結構」、「可製造」拉進同一條主線。

### Phase B - 2026-04-09 to 2026-04-12: Structural Physics, Wire, Multi-Load, Inverse Design

代表 commit：

- `0dd12759` - `feat: 加入 lift wire 軸向預壓縮分析`
- `2b7f01fa` - `feat(structure): add adjacent-segment thickness smoothness constraint`
- `f7cde593` - `feat: 新增 frozen-load aeroelastic inverse design MVP`
- 多筆 multi-load、FSI、buckling、wire compression、discrete OD post-processing commit

這個階段開始把「單純 sizing」往「可飛形狀」推：

- lift wire 不再只是邊界條件，而是會影響撓度、反力、預壓縮、failure mode 的結構元素
- thickness smoothness、discrete OD、multi-load case 開始處理製造/供應商現實
- inverse design MVP 出現，表示目標從「分析一個幾何」轉為「反推出需要做成什麼 jig shape」

工程意義：

人力飛機柔性翼不能只問「巡航時翼形長什麼樣」，還要問「地面製造 jig 要做成什麼形狀，受載後才會變成想要的翼形」。這就是重新設計敘事的核心之一。

為什麼進入下一階段：

結構可以反推 jig 之後，必須知道外形在氣動上是否仍成立。於是 commit history 轉向 AVL、dihedral、stability、VSP intake 和 validation framing。

### Phase C - 2026-04-13 to 2026-04-16: AVL, Dihedral, Stability, VSP Intake, Validation Framing

代表 commit：

- `bec147fc` - `feat: add dihedral sweep campaign script`
- `c5ed0725` - `feat: add full-body AVL model with elevator and fin for Dutch Roll analysis`
- `1c695305` - `feat(hifi): 新增 CalculiX 靜力驗證 runner`
- `M_VSP2_generic_intake_phase2` 相關 commit
- validation / inspection boundary 相關 docs

這個階段補上三件事：

1. `AVL / lightweight screening`：用快的 aero route 先做 trim / stability / beta sweep / dihedral sweep。
2. `generic VSP intake`：讓 `.vsp3` 幾何可以進入 repo，而不是靠手寫 config。
3. `validation boundary`：開始區分 internal crossval、solver verification、external validation truth。

工程意義：

這裡開始形成現行主線的雛形：先用 AVL 做大範圍快速篩選，再把 shortlist 交給更重的 VSP/VSPAero 或 inverse-design/structure route。這也避免每個粗略候選都跑昂貴且仍未 fully trusted 的 high-fidelity solver。

為什麼進入下一階段：

一旦 outer-loop 和 inverse-design 開始接起來，continuous wall-thickness 或 equivalent beam optimum 不能再當 final answer。必須把 CFRP layup、recipe、rib、manufacturing gate 變成主線輸出。

### Phase D - 2026-04-17 to 2026-04-19: Current Mainline Rewritten, CFRP / Discrete Layup / Rib Contracts

代表 commit / 文件：

- `CURRENT_MAINLINE.md` 建立正式主線
- `project_state.yaml` 建立 machine-readable truth
- `docs/dual_beam_recipe_library_architecture.md`
- `RIB_INTEGRATION_PLAN.md`
- Track L/M/N/O 類 rib foundation / bay surrogate / passive robustness / zonewise rib design
- discrete layup final design and Tsai-Wu / manufacturability surfacing

現行主線在這裡被明確重寫為：

```text
VSP / target cruise shape
-> inverse design
-> jig shape
-> realizable loaded shape
-> CFRP tube / discrete layup
-> manufacturing-feasible design
```

這個階段最重要的概念是三種 shape 分離：

- `requested cruise shape`
- `realizable cruise shape`
- `jig shape`

工程意義：

這是一個很大的設計哲學轉向。舊流程容易暗示「設計者指定的巡航形狀就是實際可飛形狀，也是製造幾何」。現在 repo 明確說這三者不能假設相同。對日本側文件而言，這是解釋「為什麼重新設計」的關鍵。

為什麼進入下一階段：

主線穩定後，團隊開始問上游：如果不是只改 Black Cat 004，下游 mainline 前面的 mission / concept / planform / airfoil search 應該怎麼做？

### Phase E - 2026-04-20 to 2026-04-24: Birdman Upstream Concept Line and High-Fidelity Mesh/SU2 Exploration

代表 commit：

- Birdman concept 設定介面、bounded CST inner loop、target-CL screening、safety gates
- Mission objective line、origin VSPAERO/SU2 integration、high-quality SU2 design
- shell_v3 / shell_v4 / half-wing BL mesh validation route
- HPA meshing package and Gmsh/SU2 route

這個階段出現兩條容易混淆的線：

1. `Birdman Upstream Concept Line`
   - 從 span、mean chord、taper、twist、spanload bias、pilot power、mass、mission 開始設計概念外形。
   - 這是上游概念設計線，不是 Black Cat downstream inverse-design 主線的替代品。
2. `mesh-native / SU2 high-fidelity side line`
   - 嘗試從 OpenVSP section 走到 Gmsh / SU2。
   - 這條線是 solver/mesh validation exploration，不是可以直接背書 CL/CD/Cm 的結果。

工程意義：

commit history 顯示團隊開始承認：如果上游概念外型本身不合理，下游 inverse-design / CFRP 再強也只是把錯誤外型做得更精緻。所以重新設計飛機必須同時處理 mission、planform、airfoil、structure，而不是只修一個 solver。

為什麼進入下一階段：

mesh/SU2 線很有價值，但還沒有物理可信度。需要把它凍結成 side-line，避免它混進主線敘事。

### Phase F - 2026-04-30 to 2026-05-01: Main-Wing Mesh-Native CFD Freeze

代表 commit：

- main-wing route productization
- VSPAERO panel reference
- mesh-native indexed wing
- Gmsh HXT / BL mesh
- SU2 marker-owned smoke
- mesh-native CFD freeze report

現行文件記錄這條線已證明：

- VSP-native section extraction 比舊 AVL-driven source 更接近設計者看到的主翼。
- 約 1.1M cell wall-resolved BL mesh 可生成並通過當時 mesh quality gate。
- SU2 可讀 mesh，marker audit pass，4-thread smoke 可跑。

但尚未證明：

- 可信 CL/CD/Cm
- grid independence
- low-Re boundary-layer / transition 合理性
- 5M+ cell 穩定生成
- half-wing symmetry route

工程意義：

這是一個重要的「不要過度宣稱」節點。對日本側說明時可以提：我們已經嘗試建立更高保真主翼 CFD 路線，但目前它是 paused side line，不拿來當設計性能背書。

### Phase G - 2026-05-02 to 2026-05-04: Birdman Mission / Span Cap / Drag Budget Refinement

代表 commit：

- fixed-range best-time objective
- 35 m span cap
- span / mean chord / taper / twist / spanload-bias design variables
- mission induced drag proxy from station `cl * chord`
- jig-shape gate with wire-relieved tip deflection
- mass cases, pilot thermal adjustment, tail volume sizing, prop efficiency assumptions
- Mission Drag Budget Contract v1

這個階段把 Birdman upstream line 從「概念參數掃描」推向「mission-aware design support」：

- objective 從單純 max range / min power，整理成 `fixed_range_best_time`
- 42.195 km 被明確寫進 mission context
- `span_m <= 35 m` 成為使用者指定工程邊界
- wing area 改由 span 和 mean chord 推出，不再用 wing loading 反推過大翼面積來過 stall gate

工程意義：

如果目標是對日本側清楚解釋「為什麼重新設計」，這段很重要：舊 run 沒有完全可行解，最佳診斷點航程約 16.1 km，與 42.195 km 還差很遠。這不代表 HPA 做不到，而是代表當前假設、airfoil、power、span cap、結構與 mission 模型必須一起重整。

### Phase H - 2026-05-05 to 2026-05-06: Airfoil Database, CST, Full-Alpha, AVL/VSP Parity

代表 commit：

- `feat: add offline CST airfoil database builder`
- `feat: make CST airfoil database search NSGA driven`
- `feat: build full-polar airfoil shortlist archive`
- `feat: support phase8 full-alpha tier builds`
- `feat: export phase7 sidecar vsp geometry`
- `docs: add Phase 7 monotone chord evaluation`
- `test: audit AVL induced drag credibility`

這個階段的核心問題是 airfoil selection 的可信度：

- 不能只用 seed airfoil 或局部 polar 點就決定全翼 airfoil。
- local Cl/Re 必須跟 actual loaded-shape AVL spanload 對齊。
- CST/NSGA/full-alpha database 不是為了堆資料，而是為了避免 selected-airfoil 在實際 loaded shape 上查表品質不足。
- AVL/VSP parity 要確認幾何輸出沒有把 twist、incidence、section schedule 搞錯。

工程意義：

這裡支持了 pipeline v2 的核心哲學：不要先選 airfoil 再問結構能不能實現。應該先知道 actual loaded shape 和 actual local Cl/Re，再做 Tier2 airfoil selection。

### Phase I - 2026-05-07: Smooth Production Baseline, Structure-Budgeted Z-State, Mass Cliff

代表 commit：

- `feat: add phase9 smooth planform jig study`
- `feat: add smooth geometry combo reoptimization`
- `feat: validate smooth production baseline`
- `feat: run smooth baseline canonical inverse check`
- `test: sweep smooth baseline z-state mass threshold`
- `feat: add structure-budgeted z-state search MVP`
- `docs: diagnose spanload structure dihedral mass`
- `test: debug z-state mass cliff selection`
- `test: debug phase13 moment closure channel`
- `docs: add dual-beam structural calibration inventory plan`

這個階段開始直接回答：「目前主翼候選到底能不能做成合理的 loaded shape？」

發現的方向包括：

- smooth geometry / production baseline 需要重新 inverse check。
- 低 Z / 低有效上反角 interpretation 會遇到 mass 或 clearance problem。
- spanload、dihedral、structure mass 之間存在 mass cliff，不是簡單調一個參數就好。
- moment ownership 和 structural selected-state alignment 需要釐清，否則 aero 和 structure 可能在不同 load-state 上各說各話。

工程意義：

這是設計重整最直接的證據之一：如果使用者期待的是 6-7 deg 低 beam-line Z 的漂亮外形，現有 coupling 下並不自然通過。這不是軟體壞掉而已，而是外形/結構/clearance 的工程衝突。

### Phase J - 2026-05-08: Phase 14 FEM/APDL, Pipeline v2, Go Mode Candidate, Phase 15/16/17 Structural Checks

代表 commit：

- `feat: 建立 Phase 14 Mac-local FEM 與 APDL package route`
- `docs: define Phase 14 FEM fidelity ladder`
- `docs: rewrite HPA wing pipeline v2 spec`
- `feat: 建立 Fourier-AVL 校準 MVP`
- `feat: 建立 structure-budgeted Z-state v2 MVP`
- `feat: 建立 loaded-shape AVL recheck MVP`
- `feat: 建立 Tier2 loaded-shape airfoil MVP`
- `feat: 建立 aero-structure closure MVP`
- `docs: package HPA wing go-mode candidate evidence`
- `fix: repair candidate FEM offset-rigid export`
- `test: 補強 phase15 load-factor 結構驗證`
- `test: 補強 phase16 ccx buckling 與 wire6 載重爬升`
- `fix: 修正 candidate shell buckling 載重步驟`

這一天把主線收成一個「可審查但不能 final sign-off」的 candidate：

```text
Mission contract
-> Fourier-AVL calibration
-> Fourier spanload candidate generation
-> smooth production geometry realization
-> AVL realization check
-> structure-budgeted loaded-Z search
-> AVL recheck on realizable loaded shape
-> Tier2 full-alpha airfoil selection
-> aero-structure closure
-> FEM/APDL / shell buckling / load-factor checks
```

工程意義：

這不是「所有問題解完」，而是第一次把 airfoil、loaded shape、structure budget、closure 和 validation package 以一條相對一致的 pipeline 收起來。它很適合拿去跟日本側說明目前狀態，也很適合指出還缺哪些工程驗證。

### Phase K - 2026-05-09: Structural Claim-Boundary / Guardrail Addendum

代表 commit：

- `feat: 新增結構 closure index`
- `feat: 新增後梁扭轉剛性 audit`
- `feat: 新增局部載荷路徑 ledger`
- `feat: 新增 rib spacing requirements`
- `feat: 新增 failure mode ordering ledger`
- `feat: 新增 detail margin input checker`
- `feat: 新增 rib bracing margin input checker`
- `feat: 新增 torsion twist closure input checker`
- `feat: 新增 full wing buckling closure input checker`
- `feat: 新增 tip deflection revalidation checker`
- `feat: 新增 wire attach 載荷分解`
- `feat: 新增 root joint 載荷 envelope`
- `feat: 新增 wire termination efficiency sensitivity`
- `feat: 補上 braced subassembly fem evidence route`
- `feat: 補上 phase44 mode shape review`
- `feat: 補上 phase45 rib spacing link review`
- `feat: 補上 local detail criticality ordering`
- `feat: 補上 root joint / wire termination / wire attach detail feasibility screen`
- `fix: 要求 rib bracing 來源可追溯`

這一波不是新的上游 aircraft concept pipeline，也不是把 detail FEM 全部做完。它的實際價值是：

- 把 rear spar stiffness、rib load transfer、wire attach local load path、root joint、
  torsion/twist、wire termination、rib spacing、tip deflection、full-wing buckling、
  failure mode ordering 這些「容易被過度宣稱」的項目整理成可審查的 evidence / blocker。
- 讓 Phase J 的 FEM/APDL / shell buckling / load-factor checks 不會被誤讀成 final aircraft sign-off。
- 把 2.5 m tip deflection 明確維持在 design-validity / submission gate，而不是斷裂點。
- 要求 full-wing 1.5G / 1.75G claim 必須有 global evidence，不能只靠 local wall buckling pass。
- 要求 rib bracing / shell bay assumption 能追到實體 station、link 或 FEM evidence，避免把 0.30 m rib-bay 當成自動成立。
- 要求 wire attach、root joint、termination、insert、bond、local tube wall 等 detail path 不只看單一 cable tensile allowable。
- 要求 failure mode ordering 在 wire 升級後重新由 global bracing / joint / detail evidence 排序。

工程意義：

Phase K 讓 candidate review 更安全，因為它會在證據不足時 fail closed；但它不是主線優先順序的替代品。
若要決定下一步是否做 rib FEM，應先問：rib / bracing assumption 是否已經會改變 Phase J pipeline
裡的 aero-structure closure candidate 排序？如果只是 final sign-off gap，它應留在 downstream validation
queue，而不是取代 mission / Fourier-AVL / smooth realization / loaded-Z / airfoil / closure 主線。

## 5. Current Aircraft Status From Latest Evidence

目前最接近 production-facing engineering review 的候選是：

```text
current_avl_compromise_conservative_closed
```

它的定位：

- `screening_closed_compromise_candidate`
- `conservative_best`
- `actual_loaded_shape_query_pass`
- `closed_for_screening`
- `daily_screening_not_final_truth`

主要數值：

| item | value |
|---|---:|
| assignment | `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g05_child_0032_70ef8136` |
| P crank | 174.600 W |
| conservative P crank | 178.882 W |
| CL | 1.16853 |
| CDi | 0.0127613 |
| e_CDi | 0.9564 |
| profile CD | 0.00936885 |
| CD0 total | 0.01325873 |
| tube mass | 10.8736 kg |
| total structural mass | 13.3736 kg |
| jig ground clearance | 42.39 mm |
| wire tension | 3024 N |
| equivalent tip deflection | 1.543 m |
| target main tip Z | 2.700 m |
| beam-line effective dihedral proxy | 8.939 deg |

它證明了：

- 在目前 contract 下，可以找到一個 aero-structure screening closed 的 conservative candidate。
- selected airfoil loopback 後 closure delta 為零，代表這個 candidate 在目前簡化流程內自洽。
- 1g、1.5g、1.75g、2g 的 internal fixed-design estimates 目前沒有顯示 tube stress 或 equivalent buckling 先爆掉。
- 第一個外推 fail mode 是 wire tension，估計約 `n = 3.030`。

它沒有證明：

- final production release
- composite local buckling sign-off
- root fitting / rib fitting / cable hardware sign-off
- nonlinear aeroelastic stability
- true aerodynamic-surface geometry dihedral equals beam-line Z proxy
- grid-independent or externally validated CL/CD/Cm

## 6. Why The Aircraft Is Being Redesigned

整理成給日本側最容易理解的版本，可以分成六個原因。

### 6.1 原本的「外形先決」假設不夠

柔性 HPA 主翼在地面 jig shape、空中 loaded shape、設計者希望的 cruise shape 之間會有差異。repo 現在明確分出三者，代表過去把它們混成一個形狀的溝通方式不再足夠。

### 6.2 Airfoil selection 必須跟 actual loaded shape 綁定

local airfoil 工作點取決於 actual local `Cl/Re`。如果先選 airfoil，再讓結構改變 loaded shape，最後 airfoil 可能其實不在原本以為的工作點。這是 pipeline v2 重寫順序的主要理由。

### 6.3 低 Z / 6-7 deg beam-line interpretation 被目前 model 擋住

最新 Go Mode package 明確指出：

- 6.0 deg / 1.804 m：mass and clearance blocker
- 6.5 deg / 1.956 m：mass and clearance blocker
- 7.0 deg / 2.108 m：clearance blocker
- 目前最低 sampled clear state 約是 2.700 m / 8.939 deg beam-line proxy

這不代表真實 6-7 deg aircraft impossible。它代表目前 beam-line contract、spanload、structure coupling 下，不能把 6-7 deg state 當成已可推進的設計。

### 6.4 Mission / pilot power / span cap 改變了上游概念設計

Birdman upstream concept line 已經把 `42.195 km`、`span_m <= 35 m`、pilot power、air density、tail sizing、prop efficiency、wing area / mean chord / taper / twist / spanload bias 放進設計空間。舊的 mass-closure run 沒有找到完全可行解，這說明要重新設計的是整個 concept space，不只是微調既有候選。

### 6.5 Continuous optimum 不能直接當 manufacturable aircraft

commit history 在 04-17 到 04-19 明確補上 CFRP / discrete layup / recipe / rib / zonewise contract。這表示設計結果必須落到可以採購、可以疊層、可以接合、可以畫圖的材料和結構語言。

### 6.6 Validation route 還沒有到 final truth

CalculiX / FEM / APDL / shell buckling 路線已經大幅補強，但最新 trust boundary 仍是：candidate-relevant equivalent-physics validation 或 local spot-check，不是 final composite aircraft sign-off。

## 7. Current Risk Register

| risk | current evidence | engineering judgement |
|---|---|---|
| Ground clearance margin too thin | current candidate jig clearance about 42.4 mm | 對建造誤差、跑道不平、wire setup、joint compliance 來說很薄，不能只靠一個數字宣稱安全 |
| Beam-line Z proxy may not equal aerodynamic surface truth | Go Mode package 明確說 Z basis 是 spar beam-line proxy | 日本側文件必須避免把 8.939 deg beam-line proxy 寫成 final aircraft dihedral |
| Wire is controlling failure mode | internal first-fail estimate `wire` at `n=3.030` | wire/cable/fitting hardware 需要工程審查，不能只看 CFRP tube stress |
| FEM scale mismatch remains | internal tip 1.5432 m vs CalculiX 1.3480 m, mismatch 12.6% | 12.6% 已比早期 94.8% mismatch 好很多，但還不能升級為 FEM-supported final margin |
| Candidate local composite effects not certified | FEM decision says it does not certify local buckling, root fittings, rib fittings, cable hardware | 需要 coupon / shell / joint / root fitting model 或外部 review |
| 6-7 deg target blocked under current contract | Go Mode package lists mass/clearance blockers | 若日本側期待低上反角，需要先釐清 beam-line vs aerodynamic surface mapping 或改結構/外形 |
| Airfoil authority warning | Fourier-AVL bridge classifies authority limitation; raw assignment rejected | 不能把 raw low Cd result 當 candidate，必須保守處理 actual loaded-shape query quality |
| High-fidelity CFD not ready for performance claim | mesh-native line is paused and lacks grid-independent CL/CD/Cm | 目前 CL/CD performance 溝通應以 AVL / proxy / VSPAero evidence boundary 說明 |
| Mission feasibility still not proven for upstream concept | old upstream run no complete feasible solution, best about 16.1 km | 新機體概念需要重新跑 mission-aware search，不能直接承諾 marathon distance |

## 8. What Is Reasonable To Tell Japan Now

可以很清楚地說：

- 我們目前有一條可追溯的 design engine，不是只靠手算或單次 CAD。
- 現在正式主線是 requested cruise shape、jig shape、realizable loaded shape 的閉環設計。
- 我們已經有一個 conservative screening candidate，可以作為日本側討論幾何、結構和製造問題的起點。
- 目前 candidate 的功率與 induced drag 數字看起來有希望，但它是 screening，不是 final sign-off。
- 下一步重點是把 beam-line geometry 對應到 aerodynamic surface、釐清 6-7 deg expectation、檢查 wire/root/rib/fitting 和 composite shell/local buckling。

不應該說：

- 這台已經完成最終設計。
- SU2/CFD 已經證明真實 drag。
- FEM 已經完全驗證 composite structure。
- 6-7 deg 狀態已經可行。
- 174-179 W crank 是最終比賽功率保證。

## 9. Recommended Structure For The Japan Concept Document

建議日本側概念文件用下面順序，會比直接引用 README 清楚很多：

1. Project objective
   - Human-powered aircraft / Birdman-style mission
   - Not only structural sizing, but whole aircraft concept and manufacturable wing design
2. Why redesign
   - Current concept space did not close mission / structure / airfoil / loaded-shape requirements simultaneously
   - Flexible wing requires inverse design and jig-shape separation
3. Current workflow
   - Mission -> spanload -> AVL screening -> loaded shape -> inverse design -> jig shape -> airfoil -> CFRP/discrete layup -> validation
4. Current candidate
   - `current_avl_compromise_conservative_closed`
   - Key power / lift / drag / mass / clearance / wire numbers
   - Explicitly label as screening candidate
5. Known issues
   - 42 mm clearance, 12.6% FEM mismatch, wire first-fail, beam-line proxy, composite/joint not certified
6. What we need from Japan-side review
   - Are span / chord / dihedral / wing area assumptions acceptable?
   - Can manufacturing tolerate the jig/clearance/wire setup?
   - What root/rib/cable fitting assumptions should be checked first?
   - What evidence level is required before calling it a design candidate?

## 10. Recommended Next Work Before Sending A Polished External Package

1. Produce a one-page geometry reference:
   - span, area, AR, mean chord, taper, selected airfoils, target Z, beam-line proxy, expected loaded deflection.
2. Build the beam-line to aerodynamic-surface mapping:
   - This is necessary before discussing 6-7 deg vs 8.939 deg with external engineers.
3. Re-run or update the mission-aware concept search under current assumptions:
   - Especially `span <= 35 m`, current pilot power, current air density, prop efficiency, tail sizing.
4. Prepare a validation status table:
   - AVL screening: current
   - VSPAero rerun: candidate/shortlist only
   - FEM/CalculiX: equivalent-physics / spot-check
   - SU2: paused, not performance truth
   - Composite/root/rib/cable hardware: still open
5. Package evidence with labels:
   - `screening`, `diagnostic`, `spot-check`, `external-validation-needed`.

## 11. Summary Judgement

從 commit history 來看，這個 repo 的進展是合理的：先建立 OpenMDAO dual-spar / load mapping / parser 基礎，再補 inverse design、AVL screening、CFRP/discrete layup、rib/wire/clearance，最後把 airfoil / loaded shape / structure budget 收成 current candidate。這條路徑符合 HPA 柔性翼設計的工程邏輯。

但目前最應該質疑的是「候選已經接近 final」這個說法。最新證據比較支持這句話：

```text
目前已有一個值得拿去幾何與結構審查的 conservative screening candidate；
但它仍被 clearance、wire、beam-line proxy、FEM scale mismatch、local composite/joint validation 卡住。
```

因此，給日本側的文件最好把重點放在：

- 我們為什麼從舊流程轉成 current mainline；
- 目前 candidate 到哪一層可信；
- 哪些工程問題還需要日本側一起審核；
- 重新設計不是否定前面成果，而是把前面 commit history 中暴露的 aero / structure / manufacturing / mission coupling 問題收斂成更正確的設計流程。
