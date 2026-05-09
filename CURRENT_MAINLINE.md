# HPA-MDO Current Mainline

> **文件性質**：目前正式主線的單一真相文件。當 README、GRAND_BLUEPRINT、
> 舊報告、歷史 prompt 互相衝突時，以這份文件為準。
> **更新基準**：2026-05-09 repo 現況；核心基準來自
> `docs/reports/2026-05-08_commit_history_report.md` 的 Phase J pipeline，
> `docs/reports/2026-05-09_phase_j_evidence_map.md` 的 stage-by-stage artifact mapping，
> `docs/reports/2026-05-09_pathfinder_basis_lock.md` 的 pathfinder geometry/load basis lock，
> `docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md` 的 all-moving tail /
> trim / stability contract insertion，
> 並納入 Phase J 後續結構宣稱 / FEM claim-boundary 補強。
> **適用對象**：使用者、協作開發者、AI agent。

## 1. 一句話版本

這個 repo 目前的正式主線不是單純的 spar sizing，也不是舊的
`VSP -> inverse design -> jig shape -> CFRP` 粗略敘事；目前主線是：

```text
Mission contract
-> tail / CG / trim / stability contract
-> Fourier-AVL calibration
-> Fourier spanload candidate generation
-> smooth production geometry realization
-> AVL realization check with full-aircraft trim / stability context
-> structure-budgeted loaded-Z search
-> AVL recheck on realizable loaded shape and all-moving tail trim
-> Tier2 full-alpha airfoil selection plus discrete tail-airfoil screening
-> aero-structure closure with tail control DOFs
-> FEM/APDL / shell buckling / load-factor / tailboom / hardware checks
```

這條線的工程目的，是把 mission requirement、spanload、可製造 smooth
geometry、loaded-Z、翼型選擇、結構預算與候選驗證收成同一條可追溯的設計鏈。

## 2. 主線操作模式：Pathfinder First, Then Expansion

目前不是要把所有 mission scan cases 一次全部推到 final FEM，也不是把單一候選說成全域最佳。
主線的正確運作模式是：

```text
pick one credible pathfinder candidate
-> make every stage physically and semantically coherent on that candidate
-> expose and repair local engineering blockers
-> only then widen the search space and rerun broader candidate families
```

這個 pathfinder candidate 的角色是「先行者」：

- 它必須能從 mission contract 追到 geometry、load、airfoil、structure、closure。
- 它用來驗證整條 pipeline 的資料契約、單位、load ownership、geometry basis 和工程語言。
- 它可以在每個 stage 做局部最佳化和局部修正。
- 它不是 hard gate、不是 final aircraft、也不是全域 optimum。
- 它閉環後，下一步才是擴大 span / AR / speed / airfoil / structure / rib-bracing search space。

目前 `current_avl_compromise_conservative_closed` 就是這個 pathfinder /
conservative screening candidate。若後續有更好的 candidate，應該用同一套 pathfinder
trace protocol 取代它，而不是另外開一條不相容敘事。

## 3. 現在主線在解什麼

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

## 4. Canonical Workflow

未來 agent 進 repo 後，請先用下面這條 pipeline 判斷任何任務的位置：

1. **Mission contract**
   - 定義任務、速度 / 功率 / span cap / mass budget / performance target。
   - 不要在 mission 還沒定義清楚時先改下游 rib、wire、tail hardware 或 FEM。
2. **Tail / CG / trim / stability contract**
   - 定義 CG range、水平尾 / 垂尾 design box、all-moving control travel、tail volume、
     static stability、control authority、tail drag/mass placeholder 與 pass/fail criteria。
   - 主翼 Fourier spanload 仍由主翼主導；尾翼在這一層是全機 feasibility / trim / stability contract。
3. **Fourier-AVL calibration**
   - 把 Fourier spanload command 與 AVL actual spanload 對齊。
   - 這是下游 structure-budgeted search 的 load authority 來源。
4. **Fourier spanload candidate generation**
   - 產生可比較的 spanload / planform / distribution 候選。
   - 這裡仍是候選生成，不是 manufacturable aircraft；尾翼只做 trim / authority feasibility filter。
5. **Smooth production geometry realization**
   - 把候選落成 smooth、可製造、可匯出的幾何語言。
   - 不能把連續 optimum 直接當圖紙；此處也要 instantiate all-moving H-tail / V-tail 幾何與 pivot axes。
6. **AVL realization check**
   - 對 realized geometry 做 full-aircraft AVL trim / stability / spanload 檢查。
   - 若 realized geometry 不能維持原本氣動意義，要回上游修正。
7. **Structure-budgeted loaded-Z search**
   - 在結構質量、clearance、wire support、beam-line Z proxy 與 loaded shape 間找可行區。
   - 這是目前 candidate 可不可推進的核心卡點之一；tail mass、trim-load envelope、tailboom load 不能被丟到最後。
8. **AVL recheck on realizable loaded shape**
   - 對真正可實現的 loaded shape 重做 full-aircraft AVL 檢查，並求 all-moving H-tail trim。
   - 不要用 requested shape 的漂亮數字替代 realizable shape。
9. **Tier2 full-alpha airfoil selection**
   - 用 actual loaded-shape 的 local `Cl/Re` 做 full-alpha airfoil selection。
   - 不能只用 seed airfoil 或單點 polar 決定全翼翼型；尾翼翼型先用 NACA 00xx / curated symmetric set 做 discrete screening，不先開 NSGA2。
10. **Aero-structure closure**
   - 檢查氣動、loaded shape、翼型、結構、clearance、wire、tail trim/control DOFs 是否在同一個候選上閉合。
   - 這一步通過才適合進更重的 FEM/APDL review。
11. **FEM/APDL / shell buckling / load-factor / tailboom / hardware checks**
    - 目前定位是 candidate-relevant equivalent-physics validation / spot-check。
    - 不等於 final composite aircraft、root fitting、wire hardware、rib joint、tail pivot 或 tailboom sign-off。

## 5. 目前做到哪裡

目前最接近 production-facing engineering review 的候選仍應理解為：

```text
current_avl_compromise_conservative_closed
```

這個 candidate 的價值是「可以拿去做幾何、結構、製造、外部審查討論的
conservative screening candidate」，不是 final design。

目前已經收斂到主線內的能力：

- Phase J pipeline 已把 mission contract、Fourier-AVL、smooth geometry、
  loaded-Z、Tier2 airfoil、aero-structure closure 與 FEM/APDL spot-check 串成同一條路。
- `ConservativeLoadMapper` 已建立 aero-grid -> structural-grid 的 opt-in conservative remap foundation；
  它守恆 total lift、root bending moment、total pitching torque，並輸出 correction / sign reversal /
  peak ratio diagnostics。它是 rib / rear-spar sensitivity 前置基礎，不是 aeroelastic sign-off。
- Empennage / trim / stability contract insertion 已建立，位置在
  `docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md`。它把 all-moving
  horizontal tail / vertical tail 定位成 trim、static stability、control authority、tailboom load、
  mission drag/mass 的共同 contract，並規定 tail airfoil 先以 discrete symmetric candidates 進入。
- Current pathfinder tail contract v0 foundation 已建立，位置在
  `configs/current_pathfinder_tail_contract_v0.yaml` 與
  `docs/reports/2026-05-09_tail_contract_v0_foundation.md`；目前 screening status 是
  `required_inputs_missing`，只完成 tail volume / reserve bookkeeping，尚未完成 full-aircraft
  trim / stability pass。
- All-moving full-aircraft tail AVL audit v0 已建立，位置在
  `docs/reports/2026-05-09_full_aircraft_tail_avl_audit_v0.md` 與
  `output/current_pathfinder_tail_avl_audit_v0/`；本機 AVL runner 已產生 9 個全機 deck /
  `.st` sweep artifact。判讀是 `blocked_by_directional_stability_or_vtail_authority`：
  `delta_H_required` 仍被 CG / wing AC 缺口擋住，`V_V = 0.010145` 且
  `C_n_beta = 0.002236` 太小，下一步應先回 tail sizing / CG / reference-moment contract，
  不應直接進 rib sensitivity。
- Current pathfinder V-tail / CG reference sizing sensitivity v0 已建立，位置在
  `scripts/vtail_cg_reference_sensitivity_v0.py`、
  `docs/reports/2026-05-09_vtail_cg_reference_sensitivity_v0.md` 與
  `output/current_pathfinder_vtail_sensitivity_v0/`；它只掃描 bounded V-tail area /
  aft-position authority，不做 rib、rear spar、ASWing-lite、FEM 或 tail airfoil NSGA2。
  15 個 AVL geometry variant 顯示放大 V-tail / 增加 tail arm 會讓 `C_n_beta` 和
  `C_n_deltaV` 往合理方向上升，但 final verdict 仍是
  `blocked_by_missing_cg_or_reference_moment`，因為 `Xref` 不是 wing AC、`Xnp` 仍只是未驗證
  neutral-point candidate，且 promoted aircraft CG range 尚未存在。
- Current pathfinder tail / CG / trim / stability screening v1 已建立，位置在
  `scripts/current_pathfinder_tail_cg_trim_stability_screening.py`、
  `docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md` 與
  `output/current_pathfinder_tail_cg_trim_stability_v1/`。它把 AVL `Xref` 明確設為每個
  screening CG row，並用 `Xnp = Xref - Cma/CLa*Cref` 驗證 neutral-point convention。
  v1 verdict 是 `ready_for_tail_aware_rib_rear_spar_sensitivity`，推薦 screening CG range
  `[0.68, 0.75] m`、H-tail `S_H=4.5 m^2 / x_ac_H=8.281 m`、V-tail
  `S_V=3.36 m^2 / x_ac_V=8.350 m`。這是 screening basis，不是 measured CG manifest、
  tail polar、tailboom/hardware、FEM 或 final aircraft sign-off。
- `scripts/fourier_avl_calibration_mvp.py` 提供 Fourier-AVL calibration artifacts；它現在要求
  明確 `--report-json`，舊 medium-search report 預設封鎖，只能用
  `--allow-legacy-medium-search` 做明確標示的歷史診斷。
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
- Current pathfinder 已有 all-moving horizontal tail / vertical tail 的 full-aircraft AVL deck /
  derivative audit v0，但尚未完成 trim、directional stability / authority、tail drag/mass budget
  或 tailboom/pivot load ownership；v0 audit 目前明確是 blocker report，不是
  aircraft-feasible sign-off。
- SU2 / mesh-native CFD 支線仍是 paused validation route，不是目前 performance claim truth。
- Rib 目前是下游 bracing / shell bay / load-transfer 實體化問題，不是主線 candidate
  generation 的短線最大優先，除非它被證明會改變 aero-structure closure 的候選排序。

## 6. Phase J 後續補強的定位

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

## 7. 下一步優先順序

目前已同意的短線順序如下：

Phase J evidence map 已重新深度審核，位置在
`docs/reports/2026-05-09_phase_j_evidence_map.md`。它現在是判斷每個 stage
目前 artifact / candidate / trust boundary 的對照表，也是舊 medium-search source 的
quarantine 文件。

Pathfinder Basis Lock 已建立，位置在
`docs/reports/2026-05-09_pathfinder_basis_lock.md`。它把
`current_avl_compromise_conservative_closed` 鎖定為 downstream screening pathfinder：
從 `smooth_tier2_production_baseline` 經 loaded-Z、loaded-shape AVL、Tier2 airfoil、
aero-structure closure 到 final candidate package 的 artifact chain 是可追溯的；但
current mission -> promoted Fourier/Fourier-AVL trace -> 這個 exact candidate 尚未鎖定，
physical aerodynamic surface / quarter-chord / clearance 也還不能等同 beam-line Z proxy。

Conservative load mapper foundation 已建立，位置在
`docs/reports/2026-05-09_conservative_load_mapper_foundation.md`。目前 current pathfinder
AVL spanload -> structural grid smoke 的 projection status 是 `conserved`，correction 很小且沒有
sign reversal；但這只代表 remap conservation foundation 可用，不代表 aeroelastic / rib / rear-spar
stiffness 已經 sign-off。

最新判讀：目前 Stage 0 mission design-space / drag-budget contract 是可用 source，且
commit history 已包含 pilot power / thermal derate、mission design-space scan、drag budget、
MissionContract / FourierTarget、airfoil sidecar、smooth geometry、loaded-Z、Tier2 airfoil
與 closure。Stage 1 Fourier-AVL calibration artifact 仍綁著 legacy medium-search top candidates；
Stage 2 machinery 存在，但還沒有一份 promoted current trace manifest 把 current mission
handoff 乾淨追到 go-mode candidate。因此 go-mode candidate 應讀成 conservative screening
candidate，而不是完整 mission -> Fourier -> smooth end-to-end final aircraft。

1. **先建立或明確標示 pathfinder promoted trace**
   - 目的：從 current mission design-space / drag-budget handoff 產生一份可提交的
     Fourier/Fourier-AVL candidate trace manifest，或明確寫出目前 go-mode candidate 是從
     `smooth_tier2_production_baseline` 開始的 downstream screening surrogate。
   - 原因：如果上游來源不清，後續 beam-line、rib、FEM 都可能在替錯誤的 candidate narrative 背書。
2. **再處理 beam-line / aerodynamic surface / clearance 對齊**
   - 目的：釐清 beam-line Z proxy、真實 aerodynamic surface、clearance、dihedral 定義是不是在同一個幾何語言下。
   - 原因：如果這層沒對齊，後面的 rib、root、wire、FEM 可能都在驗證錯對象。
3. **之後才看 aero-structure closure 的工程可信度**
   - 目的：確認 `current_avl_compromise_conservative_closed` 是否真的在同一個 geometry / load /
     airfoil / structure state 上閉合。
4. **tail contract v0 -> all-moving audit 已完成第一輪 artifact**
   - 目前：tail contract v0 foundation 已建立，且 all-moving full-aircraft AVL audit v0 已跑出
     9 個 deck / `.st` derivative artifacts。
   - 讀法：這是 blocker report，不是 pass report；它把 missing CG / wing AC 和低 V-tail 方向穩定
     evidence 變成可審查 artifact。
   - 原因：如果全機不能配平或方向穩定不足，主翼 loaded-Z / rib / FEM 局部 pass 沒有 aircraft-level
     意義。尾翼不應干擾 Fourier spanload generation，但從 mission contract 起必須存在。
5. **回補 tail sizing / CG / reference moment，再重跑 all-moving full-aircraft AVL audit**
   - 目前：v0 all-moving full-aircraft AVL audit 仍是 blocker report；v1 screening 已把
     `Xref` 明確設成 CG row，驗證 `Xnp` convention，並在 CG `[0.68, 0.75] m` 上解出
     longitudinal trim / static margin / yaw authority。v1 verdict 是
     `ready_for_tail_aware_rib_rear_spar_sensitivity`。
   - 目的：把 rib/rear-spar sensitivity 的全機 basis 固定成 screening assumption contract，
     而不是把 missing CG blocker 靜音。下一步 sensitivity 必須把 CG range、tail geometry、
     deflection reserve、tail drag/mass penalty 當輸入。
   - 原因：原始 `V_V = 0.010145` / `C_n_beta = 0.002236` tail 偏弱；v1 bounded redesign
     選用 H-tail `S_H=4.5 m^2`、V-tail `S_V=3.36 m^2`、tail x_le `8.0 m` 才讓 CG row
     有 screening margin。這不是 final geometry sign-off，只是讓下一步 stiffness sensitivity
     不再建立在一個配平/穩定性未知的 aircraft reference 上。
6. **tail-aware bounded rib/rear-spar sensitivity 已完成**
   - 目前：`scripts/tail_aware_rib_rear_spar_sensitivity.py` 與
     `docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md` 已建立。
     current pathfinder verdict 是 `ready_for_tail_aware_aeroelastic_closure`。
   - 目的：用同一個 locked pathfinder load/Z basis 跑 rear-soft/rear-stiff、finite-rib-link、
     no-rib/limited-rib 等 bounded sensitivity，確認 loaded tip Z、root-offset-removed AVL section Z、
     clearance、twist、tube mass、wire tension、`delta_H_required`、tail CL utilization、
     trim residual 與 closure ranking 會不會被 bracing 假設改變。
   - 選定 basis：`0.30 m` rib target bay 只有在 Phase24 physical station basis 下成立，
     對應 `61` half-wing stations / `121` full-wing ribs or stations、`balsa_sheet_3mm`、
     warping knockdown `0.50246`、`bounded_50pct_screening` rear-spar participation；
     對 finite-rib rear=1.0 upper-bound，選定 case 約為 `EI_flap 0.599x / GJ 0.568x`。
   - CG 限制：未補償的 selected tail delta + physical rib pack 會把 CG 推到約 `0.801 m`；
     aeroelastic closure 只能使用 final CG 管理後的 `0.75 m` screening row。需要約
     `0.091 m` forward rebalance on 56 kg equivalent pilot/cockpit mass；不能把 tail/rib mass
     加上去後還沿用舊 ready verdict。
   - load 前提：使用 conservative remap diagnostics 檢查 total lift、root bending moment、torque
     是否守恆；如果出現 large correction 或 unphysical status，先降級 loading confidence，不要直接進 rib sensitivity。
   - 原因：現有 Phase32 / structural closure evidence 已顯示 rear spar / rib assumptions
     會大幅移動 response；若先跑 ASWing，可能只是把錯的 stiffness basis 耦合得更漂亮。
     FEM detail 則應吃已鎖定的 load/geometry envelope，不應先決定哪個 beam-line / aero-surface
     state 才是真正設計狀態。
   - 後續順序：tail / CG / trim / stability screening v1 basis ->
     tail-aware bounded rib/rear-spar sensitivity (done) -> elastic twist / `alpha_eff` + trim audit ->
     ASWing-like / equivalent tail-aware aeroelastic coupling -> root/wire/termination/rib/tail hardware FEM detail。

針對已鎖定的 downstream pathfinder engineering lane，`ConservativeLoadMapper` foundation
是 load ownership 前置基礎且已完成；tail / CG / trim / stability contract v0、all-moving
full-aircraft AVL audit v0、V-tail / CG reference sizing sensitivity v0、以及 tail / CG /
trim / stability screening v1 也已完成。tail-aware bounded rib / rear-spar stiffness
sensitivity 已完成並選出下一階段 basis；接下來要做 elastic twist / `alpha_eff` + trim audit
與 tail-aware aeroelastic closure。這個 ready verdict 仍是 screening ready，不是 final
CG/mass contract、tail polar、ASWing-like coupling、FEM 或硬體 sign-off；尤其 CG 必須使用
final managed row，而不是未補償的 tail/rib mass shift。

可直接用於新 goal 的 objective：

```text
在 /Volumes/Samsung SSD/hpa-mdo 以 `docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md` 為起點，執行下一步 elastic twist / `alpha_eff` + trim audit 與 tail-aware aeroelastic closure。必須使用 selected basis：`0.30 m` physical rib station basis、`bounded_50pct_screening` rear-spar participation、warping knockdown `0.50246`、final managed CG row `0.75 m`、tail CD0 penalty `+0.002352`、tail mass delta `+1.17 kg`；不能把未補償 CG=`0.801 m` 的 mass bookkeeping 當成 ready。
```

## 8. 常用入口與角色

### A. Mission / upstream concept

- 入口：`scripts/birdman_upstream_concept_design.py`
- 角色：從 mission、pilot power、span cap、mass case、planform / twist / spanload bias
  產生上游概念候選。
- 注意：這條線是 mission contract 的上游來源之一，不是 FEM validation。

### B. Fourier-AVL / pipeline v2

- 入口：`scripts/fourier_avl_calibration_mvp.py`
- 角色：建立 Fourier command 與 AVL actual spanload 的 calibration evidence。
- 注意：必須明確指定 current `--report-json`。舊
  `birdman_mission_coupled_medium_search_20260503` 只可用於 legacy diagnostics，不能當 pathfinder evidence。

### C. Smooth geometry / loaded-Z / closure

- 入口：
  - `scripts/structure_budgeted_z_state_search.py`
  - `scripts/aero_structure_closure_mvp.py`
  - `scripts/direct_dual_beam_inverse_design.py`
- 角色：把 realized geometry、loaded-Z search、inverse route、Tier2 airfoil 與 closure 接起來。

### D. Empennage / trim / stability

- 入口：
  - `docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md`
  - `docs/reports/2026-05-09_tail_cg_trim_stability_screening_v1.md`
  - `scripts/current_pathfinder_tail_cg_trim_stability_screening.py`
  - `src/hpa_mdo/concept/safety.py::evaluate_trim_balance`
  - `src/hpa_mdo/aero/avl_exporter.py`
  - `src/hpa_mdo/aero/avl_stability_parser.py`
- 角色：把 all-moving horizontal tail / vertical tail 變成全機 trim、static stability、
  control authority、tail drag/mass、tailboom load 的 screening contract。
- 注意：v1 已可作為 tail-aware rib / rear-spar sensitivity 的 screening basis；仍不是 full
  flight dynamics、measured CG/mass manifest，也不是 tail hardware sign-off。

### E. Tail-aware rib / rear-spar sensitivity

- 入口：
  - `scripts/tail_aware_rib_rear_spar_sensitivity.py`
  - `docs/reports/2026-05-09_tail_aware_rib_rear_spar_sensitivity.md`
- 角色：把 committed tail/CG basis、physical rib station basis、rear-spar participation、
  warping knockdown、mass/CG bookkeeping 與 closure ranking 接成下一步 aeroelastic closure
  的 screening basis。
- 注意：目前 verdict 是 `ready_for_tail_aware_aeroelastic_closure`，但只在 final CG managed
  row `0.75 m` 下成立；未補償 tail+ribs mass CG 約 `0.801 m`，不能靜音。

### F. FEM/APDL / shell / load-factor spot-check

- 入口：
  - `scripts/phase14_maclocal_fem_package.py`
  - `scripts/phase15_candidate_load_factor_buckling_check.py`
  - `scripts/phase16_ccx_buckling_wire6_ramp.py`
  - `scripts/phase17_candidate_shell_buckling_tip_review.py`
- 角色：candidate-relevant equivalent-physics validation / review package。
- 注意：這不是 final composite/root/wire/rib/hardware certification。

### G. Drawing-ready package

- 入口：`scripts/export_drawing_ready_package.py`
- 角色：把可畫圖 artifact 收成 handoff package。
- 注意：drawing handoff boundary 不等於 external validation boundary。

### H. Producer / decision interface

- 入口：`python -m hpa_mdo.producer`
- 角色：提供外部 consumer / automation 用 machine-readable contract。
- 注意：它是 integration boundary，不是主 physics 問題本身。

## 9. 現在不該再當主線的敘事

- `equivalent_beam` 作為正式 structural truth。
- 把 repo 描述成單純 OpenMDAO spar optimizer。
- 把 continuous wall-thickness optimum 直接當 manufacturable aircraft。
- 把 old README / old prompt 的 `VSP -> inverse design -> CFRP` 當完整主線。
- 把 producer / decision interface 當成 physics 主線本體。
- 把 rib、wire hardware、root fitting detail FEM 提前成上游 candidate-generation 主線，
  除非它們已被證明會改變 aero-structure closure 的候選排序。
- 把 horizontal / vertical tail 當成最後 FEM 才補的外觀件，或把 AVL hinged-control proxy
  當成 all-moving tail 的 production model。
- 把 `birdman_mission_coupled_medium_search_20260503`、`sample_1476`、`233 W`、`8642.9 m`
  當成 current mission evidence。
- 把舊的一維、舊 CFRP、legacy refresh、研究型 script output 當成目前 pathfinder 的 production truth。

## 10. 對未來 AI Agent 的工作規則

1. 先讀這份 `CURRENT_MAINLINE.md`，再讀 `README.md`。
2. 需要 commit-history truth 時，讀
   `docs/reports/2026-05-08_commit_history_report.md`，特別是 Phase J 和後續 addendum。
   需要逐 stage artifact / trust boundary 時，再讀
   `docs/reports/2026-05-09_phase_j_evidence_map.md`。
3. 不要用舊 prompt、舊 task pack 或舊 README 段落覆蓋 Phase J pipeline。
4. 若要使用舊 module / 舊 output，先判斷它屬於 current pathfinder evidence、
   reusable module / tool、legacy diagnostic，還是 quarantined source。只有第一類可以直接用於目前主線；
   第二類必須重新接 current contract；第三、四類不能變成 current claim。
5. 如果完成一系列同屬同一個 idea 的任務，而且它改變了目前主線、可用狀態、信任邊界或下一步優先順序，
   必須同步更新 `README.md` 和 / 或 `CURRENT_MAINLINE.md`。
6. 如果只做局部 test / script guardrail，請在文件中說清楚它是 claim-boundary / diagnostic，
   還是真正工程 validation。
7. 遇到工程問題時，不要只用軟體測試通過作結論；要用該領域工程師角度檢查物理假設是否合理。

## 11. 暫停中的主翼 mesh-native CFD / SU2 支線

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
