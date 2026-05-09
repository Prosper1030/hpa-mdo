# HPA-MDO Current Mainline

> **文件性質**：目前正式主線的單一真相文件。當 README、GRAND_BLUEPRINT、
> 舊報告、歷史 prompt 互相衝突時，以這份文件為準。
> **更新基準**：2026-05-09 repo 現況；核心基準來自
> `docs/reports/2026-05-08_commit_history_report.md` 的 Phase J pipeline，
> 並納入 Phase J 後續結構宣稱 / FEM claim-boundary 補強。
> **適用對象**：使用者、協作開發者、AI agent。

## 1. 一句話版本

這個 repo 目前的正式主線不是單純的 spar sizing，也不是舊的
`VSP -> inverse design -> jig shape -> CFRP` 粗略敘事；目前主線是：

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

這條線的工程目的，是把 mission requirement、spanload、可製造 smooth
geometry、loaded-Z、翼型選擇、結構預算與候選驗證收成同一條可追溯的設計鏈。

## 2. 現在主線在解什麼

目前核心問題不是「給定一個漂亮幾何後把 spar 做到 pass」，而是：

- mission contract 能否導出可信的 Fourier / AVL spanload 候選；
- 候選能否落成 smooth production geometry，而不是只停在數學分布；
- smooth geometry 經 AVL realization check 後，是否仍符合氣動 / trim / 載荷需求；
- structure-budgeted loaded-Z search 能否找到 mass、clearance、wire、shape 都能接受的
  realizable loaded shape；
- Tier2 full-alpha airfoil selection 是否在 actual loaded-shape 的 local `Cl/Re`
  上仍有足夠查表品質與失速裕度；
- aero-structure closure 是否真的閉合，而不是氣動和結構各自 pass 不同狀態；
- 最後的 FEM/APDL、shell buckling、load-factor checks 能否支持 candidate-relevant
  review，同時避免把 spot-check 誤寫成 final aircraft sign-off。

## 3. Canonical Workflow

未來 agent 進 repo 後，請先用下面這條 pipeline 判斷任何任務的位置：

1. **Mission contract**
   - 定義任務、速度 / 功率 / span cap / mass budget / performance target。
   - 不要在 mission 還沒定義清楚時先改下游 rib、wire 或 FEM。
2. **Fourier-AVL calibration**
   - 把 Fourier spanload command 與 AVL actual spanload 對齊。
   - 這是下游 structure-budgeted search 的 load authority 來源。
3. **Fourier spanload candidate generation**
   - 產生可比較的 spanload / planform / distribution 候選。
   - 這裡仍是候選生成，不是 manufacturable aircraft。
4. **Smooth production geometry realization**
   - 把候選落成 smooth、可製造、可匯出的幾何語言。
   - 不能把連續 optimum 直接當圖紙。
5. **AVL realization check**
   - 對 realized geometry 做 AVL trim / stability / spanload 檢查。
   - 若 realized geometry 不能維持原本氣動意義，要回上游修正。
6. **Structure-budgeted loaded-Z search**
   - 在結構質量、clearance、wire support、beam-line Z proxy 與 loaded shape 間找可行區。
   - 這是目前 candidate 可不可推進的核心卡點之一。
7. **AVL recheck on realizable loaded shape**
   - 對真正可實現的 loaded shape 重做 AVL 檢查。
   - 不要用 requested shape 的漂亮數字替代 realizable shape。
8. **Tier2 full-alpha airfoil selection**
   - 用 actual loaded-shape 的 local `Cl/Re` 做 full-alpha airfoil selection。
   - 不能只用 seed airfoil 或單點 polar 決定全翼翼型。
9. **Aero-structure closure**
   - 檢查氣動、loaded shape、翼型、結構、clearance、wire 是否在同一個候選上閉合。
   - 這一步通過才適合進更重的 FEM/APDL review。
10. **FEM/APDL / shell buckling / load-factor checks**
    - 目前定位是 candidate-relevant equivalent-physics validation / spot-check。
    - 不等於 final composite aircraft、root fitting、wire hardware、rib joint sign-off。

## 4. 目前做到哪裡

目前最接近 production-facing engineering review 的候選仍應理解為：

```text
current_avl_compromise_conservative_closed
```

這個 candidate 的價值是「可以拿去做幾何、結構、製造、外部審查討論的
conservative screening candidate」，不是 final design。

目前已經收斂到主線內的能力：

- Phase J pipeline 已把 mission contract、Fourier-AVL、smooth geometry、
  loaded-Z、Tier2 airfoil、aero-structure closure 與 FEM/APDL spot-check 串成同一條路。
- `scripts/fourier_avl_calibration_mvp.py` 提供 Fourier-AVL calibration artifacts。
- `scripts/structure_budgeted_z_state_search.py` 提供 structure-budgeted loaded-Z search。
- `scripts/aero_structure_closure_mvp.py` 提供 Tier2 後的 aero-structure closure。
- Phase 14 Mac-local FEM / APDL package route 已建立，且修掉早期 FEM offset-rigid
  export 類錯配。
- Phase 15/16/17 load-factor、wire6 ramp、candidate shell buckling / tip limit review
  已把一部分候選驗證包接起來。

目前仍不能宣稱完成的地方：

- FEM/CalculiX 仍有 model-basis / displacement-scale mismatch 風險，不能當 final validation。
- Composite local buckling、root fitting、wire/cable termination、attach hardware、rib joint
  仍需要更高可信度的 detail model、coupon、外部工程審查或 FEM。
- Ground clearance margin 對製造誤差、跑道不平、wire setup、joint compliance 仍偏薄。
- Beam-line Z proxy 還不能直接等同 aerodynamic surface / final aircraft dihedral。
- SU2 / mesh-native CFD 支線仍是 paused validation route，不是目前 performance claim truth。
- Rib 目前是下游 bracing / shell bay / load-transfer 實體化問題，不是主線 candidate
  generation 的短線最大優先，除非它被證明會改變 aero-structure closure 的候選排序。

## 5. Phase J 後續補強的定位

Phase J 之後新增了一系列 structural claim-boundary / engineering guardrail。這些工作有價值，
但要正確理解：

- 它們主要防止 repo 把局部 pass 誤寫成 full-wing / final aircraft pass。
- 它們把 rear spar stiffness、rib bracing、wire attach、root joint、torsion/twist、
  wire termination、rib spacing、tip deflection、full-wing buckling、failure ordering
  的 evidence gap 明確化。
- 它們不是把所有 detail FEM / joint / hardware validation 做完。

已補強的工程檢查族群：

- structural claim readiness：避免把 local / screening evidence 升格成 final sign-off。
- local load path ledger：拆出 wire attach、root joint、termination、tube wall 等 detail path。
- rear spar / rib bracing diagnostics：檢查 rear spar、rib spacing、braced subassembly 證據是否足以支撐 buckling bay assumption。
- torsion / twist closure inputs：要求 aeroelastic twist / torsional stiffness 的來源可追溯。
- full-wing buckling claim boundary：要求 1.5G / 1.75G full-wing claim 有 global evidence，而不是只靠 local wall pass。
- tip deflection claim boundary：把 2.5 m gate 定位成 design-validity / submission gate，不是斷裂點。
- failure mode ordering：wire 升級後，不再假設 wire 一定是第一 blocker，必須由 global bracing / joint FEM 排序。

工程判斷：這一波補強使 candidate review 更安全、更不容易過度宣稱；但下一個大步仍應回到主
pipeline，確認目前 candidate 的 mission / Fourier-AVL / smooth realization / loaded-Z / airfoil /
closure 是否該繼續推進，而不是直接把 rib detail FEM 當作新主線。

## 6. 常用入口與角色

### A. Mission / upstream concept

- 入口：`scripts/birdman_upstream_concept_design.py`
- 角色：從 mission、pilot power、span cap、mass case、planform / twist / spanload bias
  產生上游概念候選。
- 注意：這條線是 mission contract 的上游來源之一，不是 FEM validation。

### B. Fourier-AVL / pipeline v2

- 入口：`scripts/fourier_avl_calibration_mvp.py`
- 角色：建立 Fourier command 與 AVL actual spanload 的 calibration evidence。

### C. Smooth geometry / loaded-Z / closure

- 入口：
  - `scripts/structure_budgeted_z_state_search.py`
  - `scripts/aero_structure_closure_mvp.py`
  - `scripts/direct_dual_beam_inverse_design.py`
- 角色：把 realized geometry、loaded-Z search、inverse route、Tier2 airfoil 與 closure 接起來。

### D. FEM/APDL / shell / load-factor spot-check

- 入口：
  - `scripts/phase14_maclocal_fem_package.py`
  - `scripts/phase15_candidate_load_factor_buckling_check.py`
  - `scripts/phase16_ccx_buckling_wire6_ramp.py`
  - `scripts/phase17_candidate_shell_buckling_tip_review.py`
- 角色：candidate-relevant equivalent-physics validation / review package。
- 注意：這不是 final composite/root/wire/rib/hardware certification。

### E. Drawing-ready package

- 入口：`scripts/export_drawing_ready_package.py`
- 角色：把可畫圖 artifact 收成 handoff package。
- 注意：drawing handoff boundary 不等於 external validation boundary。

### F. Producer / decision interface

- 入口：`python -m hpa_mdo.producer`
- 角色：提供外部 consumer / automation 用 machine-readable contract。
- 注意：它是 integration boundary，不是主 physics 問題本身。

## 7. 現在不該再當主線的敘事

- `equivalent_beam` 作為正式 structural truth。
- 把 repo 描述成單純 OpenMDAO spar optimizer。
- 把 continuous wall-thickness optimum 直接當 manufacturable aircraft。
- 把 old README / old prompt 的 `VSP -> inverse design -> CFRP` 當完整主線。
- 把 producer / decision interface 當成 physics 主線本體。
- 把 rib、wire hardware、root fitting detail FEM 提前成上游 candidate-generation 主線，
  除非它們已被證明會改變 aero-structure closure 的候選排序。

## 8. 對未來 AI Agent 的工作規則

1. 先讀這份 `CURRENT_MAINLINE.md`，再讀 `README.md`。
2. 需要 commit-history truth 時，讀
   `docs/reports/2026-05-08_commit_history_report.md`，特別是 Phase J 和後續 addendum。
3. 不要用舊 prompt、舊 task pack 或舊 README 段落覆蓋 Phase J pipeline。
4. 如果完成一系列同屬同一個 idea 的任務，而且它改變了目前主線、可用狀態、信任邊界或下一步優先順序，
   必須同步更新 `README.md` 和 / 或 `CURRENT_MAINLINE.md`。
5. 如果只做局部 test / script guardrail，請在文件中說清楚它是 claim-boundary / diagnostic，
   還是真正工程 validation。
6. 遇到工程問題時，不要只用軟體測試通過作結論；要用該領域工程師角度檢查物理假設是否合理。

## 9. 暫停中的主翼 mesh-native CFD / SU2 支線

這不是目前正式主線，也不是可用來背書人力飛機性能的 CFD 結果。它是 2026-05-01 凍結下來的高保真氣動支線：

```text
OpenVSP main-wing sections
  -> mesh-native indexed wing
  -> Gmsh HXT / boundary-layer mesh
  -> SU2 marker-owned smoke
```

目前已證明：

- VSP-native section extraction 比舊 AVL-driven source 更接近設計者在 VSP 看到的主翼；
- 1.1M 級 wall-resolved BL mesh 可以生成並通過目前 mesh quality gate；
- SU2 可讀 mesh，`wing_wall` / `farfield` marker audit pass，4-thread smoke 可執行。

目前尚未證明：

- 可信 CL/CD/Cm；
- grid independence；
- 人力飛機低雷諾數 / boundary-layer / transition 物理合理；
- 5M+ cell 等級網格可穩定生成；
- half-wing symmetry route。

若未來 agent 要接這條線，先讀：

```text
hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md
```

不要從舊 STEP/BREP repair 報告或單次 SU2 smoke 直接開始改。
