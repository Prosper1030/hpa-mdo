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
- Composite local buckling、root fitting、wire/cable termination、attach hardware 仍需要更高可信度的
  detail model、coupon、外部工程審查或 FEM。P1 C04 rib joint 已有 saddle-ring/yoke/clamp
  local load-path closure，可進 coupon/local FEM；這仍不是 rib-joint final sign-off。
- Ground clearance margin 對製造誤差、跑道不平、wire setup、joint compliance 仍偏薄。
- Beam-line Z proxy 還不能直接等同 aerodynamic surface / final aircraft dihedral。
- Current pathfinder 已有 all-moving horizontal tail / vertical tail 的 full-aircraft AVL deck /
  derivative audit、tail/CG/trim/stability screening、tail-aware closure 與 P1 mass-integrated
  closure evidence。managed CG row 下 trim / static / directional authority pass，但 tailboom/pivot
  hardware、measured mass manifest 與 final flight-dynamics sign-off 尚未完成。
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
     current pathfinder balsa baseline verdict 是 `ready_for_tail_aware_aeroelastic_closure`；
     同一個 report 現在也輸出 material family sensitivity verdict。
   - 目的：用同一個 locked pathfinder load/Z basis 跑 rear-soft/rear-stiff、finite-rib-link、
     no-rib/limited-rib 等 bounded sensitivity，確認 loaded tip Z、root-offset-removed AVL section Z、
     clearance、twist、tube mass、wire tension、`delta_H_required`、tail CL utilization、
     trim residual 與 closure ranking 會不會被 bracing 假設改變。
   - 選定 basis：`0.30 m` rib target bay 只有在 Phase24 physical station basis 下成立，
     對應 `61` half-wing stations / `121` full-wing ribs or stations、`balsa_sheet_3mm`、
     warping knockdown `0.50246`、`bounded_50pct_screening` rear-spar participation；
     對 finite-rib rear=1.0 upper-bound，選定 case 約為 `EI_flap 0.599x / GJ 0.568x`。
   - material family sensitivity：`balsa_sheet_3mm` 保留為 baseline；新增 foam-only
     `eps_hd_foam_cnc_10mm`、`xps_high_compressive_cnc_10mm`、`structural_foam_cnc_10mm`。
     v1 不包含 EPS+balsa、glass cap 或 carbon cap hybrid credit。latest verdict 是
     `foam_only_families_do_not_clear_current_aeroelastic_closure`：EPS/XPS effective GJ 約為
     balsa selected basis 的 `0.163x`、projected twist 約 `33.16 deg`；structural foam 約
     `0.581x`、projected twist 約 `9.32 deg`。三者都沒有過 `3 deg` twist screening bound。
   - stiffness rework candidates：同一 runner 現在另外輸出
     `stiffness_rework_candidates`，把 foam-only reference 與下一輪 stiffness rework 分開。
     balsa baseline 保留比較用；`eps_balsa_cap_hybrid_10mm`、
     `structural_foam_glass_face_10mm` 和 stronger rear-spar participation / shear-transfer
     rows 是可重跑的下一版 candidate family，不是 final closure pass。
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
   - tail-aware aeroelastic closure baseline 已完成第一輪：`scripts/tail_aware_aeroelastic_closure.py`
     與 `docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md` 顯示 fixed-point loop
     3 次收斂，final managed CG `0.75 m`、H-tail reserve、static margin、V-tail authority、
     mass/drag/power charge 與 conserved load remap 都保留；但 direct spar-pair rotation
     -> AVL incidence stress-test 給出 max twist 約 `5.413 deg`，超過 `3 deg` screening
     bound。新增 twist-source audit 顯示 elastic-axis / quarter-chord consistent projection
     仍約 `5.413 deg`，conservative bounded physical projection 約 `3.256 deg`，peak
     y≈`2.328 m`，主因是 aerodynamic torque-only 分量；lift 在該 station 部分抵消。
     baseline closure verdict 仍是 `needs_aeroelastic_geometry_or_stiffness_rework`，但
     clear twist-source verdict 是 `ready_for_hybrid_rib_stiffness_rework`。
   - 後續順序：tail / CG / trim / stability screening v1 basis ->
     tail-aware bounded rib/rear-spar sensitivity (done) -> tail-aware aeroelastic closure baseline
     (done, twist-source audit done) -> materialized rib station/bay contract audit (done) ->
     hybrid rib / shear cap / skin / bounded rear-spar participation rerun (done for selected
     hybrid screening surrogate) -> qualified aero-surface mapping plus local FEM/coupon package ->
     root/wire/termination/rib/tail hardware FEM detail。
   - Current pathfinder materialized rib contract audit 已建立：`scripts/current_pathfinder_materialized_rib_contract_audit.py`
     與 `docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md`
     會輸出 `rib_station_table.csv`、`rib_bay_table.csv`、mandatory/missing contract、
     skin sag、bond/collar risk 與 `local_fem_trigger_report.json`。它確認 `121` full-wing
     stations / `120` bays 已 materialized，max bay `0.297063 m`；但 verdict 是
     `blocked_needs_materialized_bond_shape_data`，因為 transport joint、control station、
     airfoil/twist transition 是 `missing_contract`，skin sag 是 `unknown_requires_test`，
     bond/collar/spar contact 是 `needs_data`，y≈`2.328 m` 附近必須作 torque-critical
     local FEM / hybrid reinforcement zone。這一步是 hybrid stiffness rework 的前置基礎，
     不能被 warping-knockdown tuning 或 foam-only EPS/XPS pass claim 取代。
   - Current pathfinder rib / torsion rework verdict 已建立：
     `scripts/current_pathfinder_rib_torsion_rework_verdict.py` 與
     `docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md`
     把 sensitivity、tail-aware closure、materialized rib audit 接成下一階段 gate。
     verdict 是 `candidate_ready_for_local_FEM_and_coupon_before_FEM_package`，不是
     `ready_for_FEM_loadcase_package`。選出的下一個 local FEM/coupon candidate 是
     `eps_balsa_cap_hybrid_10mm + bounded_65pct_screening`。closure runner 現在會把
     selected hybrid effective-GJ 當作 main/rear torsion-cell screening surrogate 消耗，
     actual closure bounded physical twist 是 `2.070 deg`，低於 `3 deg` bound；direct
     stress-test 從 baseline `5.413 deg` 降到 `3.449 deg`，仍是 conservative mapping
     warning，不是 final aero-surface twist signoff。rib mass 約 `5.365 kg`，比 balsa
     baseline 多 `2.335 kg`，且 CG/rebalance 已計入。後續 P1 closure 已把 C04
     bond/collar blocker 推進到 saddle-ring/yoke/clamp load-path pass 並回灌 splice/collar
     mass；但 transition/control stations、C07 skin sag process、coupon/local FEM 和
     hardware/laminate detail 仍不是 final sign-off。positive-zone package 已推進到
     `scripts/current_pathfinder_positive_torque_zone_validation_package.py` 與
     `docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md`：
     R067/R068/R069 與 B066-B069 是 active validation set，R066/R070 是 local model
     boundary；critical R068 的 extracted local load row 是 main lift `21.202 N`、
     kernel torque `-12.716 N*m`，轉成 main/rear torque-couple `-23.839 / +23.839 N`。
     package verdict 是
     `positive_zone_ready_for_local_FEM_and_coupon_definition_not_margin_pass`，並輸出
     guarded APDL skeleton、station/bay manifest、load decomposition、coupon matrix、
     missing-data register。這不是 FEM margin pass；下一步是補 supplier/coupon
     allowables 與 collar/tube-wall/bond/cap/skin dimensions 後跑 local margin，再 mirror
     negative zone。
   - Current pathfinder rib / torsion fast design-search loop 已重新校準：
     `scripts/current_pathfinder_rib_torsion_design_search.py` 與
     `docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md`。
     這一步把 rib/core thickness、material family、zone spacing、local cap/face/collar
     reinforcement、rear-spar participation `0.50 / 0.65 / 0.75`、mass/CG/tail-trim
     trade 和 manufacturability 接成可重跑 search runner，並輸出 Pareto / shortlist、
     FEM calibration samples、APDL/CalculiX calibration skeletons 與 FEM-result 回填
     interface。fast physical model 現在是 `link_limited_torsion_cell_v2`：rib thickness、
     spacing 與 collar credit 被視為 shear-transfer link terms，不再把 carbon collar /
     relaxed spacing 當成完整 torsion-cell GJ 乘數。revised fast-loop selected row 變成
     `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`；
     fast bounded twist 約 `1.674 deg`。原本 relaxed 10 mm carbon-collar row 仍保留為
     representative `selected_hybrid_10mm` FEM sample，另加 revised selected candidate sample。
     EPS/XPS foam-only 仍只可作 shape-core / lightweight reference，不可作 structural bracing pass。
   - Rib / torsion fast-loop CCX local-frame physical alignment 已建立：
     `scripts/current_pathfinder_rib_torsion_fem_calibration.py` 與
     `docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md`。
     這一步已把 CalculiX/CCX 從 2-node smoke 升級成 local beam-frame calibration
     solver：main/rear spar segment、torque-zone collar、rib shear-transfer /
     diagonal shear-transfer beams、y=`2.327757 m` local lift 與 main/rear
     torque-couple 都寫進 sample decks，並新增 local bay-end reaction print / audit。
     CCX local model audit 判定 `ccx_local_model_reasonable_for_fast_physics_alignment`：
     load couple recovers `12.716 N*m` torque、reaction force balance closed、deformation
     mode 是 torsion / shear-transfer dominant、selected/aggressive stiffness ratio
     符合工程直覺。這次不再使用 hidden family correction factor；`family_correction_factors`
     保持空值，只保留 legacy diagnostic factors。代表 structural rows 的 revised
     fast-vs-CCX error 已壓到 `<=5%`：原 relaxed 10 mm selected row `4.554%`、
     aggressive carbon/glass collar row `1.171%`、revised selected row `1.950%`。
     verdict 是 `fast_physical_model_verified_within_5pct`。y≈`2.328 m`
     bond/collar/tube-wall 仍是 `watch`，tube-wall margin 約 `2.304`；這個 simplified
     CCX model 只代表 local torsional stiffness / shear-transfer response，不是 bond peel /
     buckling / tube-wall / skin sag / flight-load final truth。
   - Current pathfinder rib / torsion detailed local validation shortlist 已鎖定：
     `docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md`。
     verdict 是 `selected_candidate_ready_for_detailed_local_validation`，不是 final pass。
     鎖定 basis 是 revised fast-loop selected row
     `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
     with revised bounded twist `1.673592 deg`。detailed validation shortlist 只保留三個
     local FEM/coupon cases：P1 selected 10 mm uniform carbon-collar row、P2 12 mm
     uniform carbon-collar heavier reserve、P3 10 mm uniform glass-face collar lower-complexity
     alternate。8 mm dense torque-zone row 雖較輕，但因 manufacturability score 降到
     `0.38` 且 direct fast twist 接近 `3 deg`，不升為 detailed validation priority。下一層
     必須針對 y≈`2.328 m` rib/collar/bond/tube-wall、skin sag、rib-to-spar shear/peel、
     carbon/glass collar與 balsa cap load path、tube crush/ovalization，以及代表 ordinary bay
     做 detailed FEM/coupon/allowable；這仍不是 aircraft, FEM/APDL, adhesive, tube-wall,
     skin sag, buckling, or manufacturing sign-off。

針對已鎖定的 downstream pathfinder engineering lane，`ConservativeLoadMapper` foundation
是 load ownership 前置基礎且已完成；tail / CG / trim / stability contract v0、all-moving
full-aircraft AVL audit v0、V-tail / CG reference sizing sensitivity v0、以及 tail / CG /
trim / stability screening v1 也已完成。tail-aware bounded rib / rear-spar stiffness
sensitivity 已完成並選出下一階段 basis；tail-aware aeroelastic closure baseline 第一輪已收斂但
verdict 是 `needs_aeroelastic_geometry_or_stiffness_rework`。rib / torsion rework verdict
已把 selected hybrid effective-GJ 接進 structural kernel / closure rerun，bounded physical
twist 實際清到 `2.070 deg`；positive y≈`2.328 m` package 已定義 local FEM/coupon
handoff，但還不能進 FEM/APDL margin package。下一步不是擴大 search，而是填這份
positive-zone package 的 supplier/coupon allowables 與 geometry detail，跑
rib cap/face/collar/bond/tube-wall local margin、skin sag coupon/panel evidence，之後
mirror/compare negative zone；同時 direct `3.449 deg` stress-test 仍要做 qualified
aero-surface mapping。
新的 fast design-search loop 已完成 CCX local-frame physical alignment：代表 structural
rows 已在 local CCX beam-frame 內對齊到 `<=5%`，revised search 選出 uniform `0.30 m`
carbon-collar / rear75 的 10 mm hybrid row，bounded twist 約 `1.674 deg`。這仍不能取代
positive-zone local margin、coupon work、skin sag evidence 或 APDL/CalculiX final sign-off。
Detailed local validation shortlist 已把這個 selected row 鎖成 P1，並把 12 mm carbon-collar
reserve 與 10 mm glass-face collar manufacturability fallback 列成 P2/P3；目前 verdict 只到
`selected_candidate_ready_for_detailed_local_validation`。

**Step 1 — Geometry and allowable freeze sheet 已完成（2026-05-11）：**
`scripts/current_pathfinder_rib_local_detail_geometry_freeze.py` 已從 config
thickness-fraction 推導出 y≈2.328 m 的 spar tube OD/wall（main CF-HM-100x98 100 mm /
rear CF-HM-80x78 80 mm），填入全部八個 missing-data-register items（adhesive、
bondline、collar、balsa cap、EPS、skin），並對 7 個 local failure modes 做 preliminary
margin screen。所有 preliminary margin 均 pass；最緊的是 **C07 skin sag（margin 0.03）**
與 **C04 bond peel（margin 2.57）**。C07 的緊是因為 process-sensitive pre-strain 假設，
不是強度不足；adhesive / tube-wall / collar bearing 的裕度極大，這與 HPA 超輕載荷
吻合。APDL skeleton 的所有 `= -1` placeholder 已用 v1 freeze 值填入，guarded flag
改成 `SUPPLIER_DATA_REQUIRED = 0`。freeze sheet 位於
`output/current_pathfinder_rib_local_detail_geometry_freeze/geometry_allowable_freeze.json`
與 `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md`。
12 個 tests 通過。

**Step 2 — Refined analytical margin run 已完成（2026-05-11）：**
`scripts/current_pathfinder_rib_local_detail_margin_run.py` 讀入 Step 1 freeze JSON，
對 7 個 failure modes 套用精化力學模型：C02/C03 Goland-Reissner 簡化 SCF（bond shear
端部集中）、C04 偏心力矩模型（M = F × r_spar）取代 0.20 fraction proxy、C05 Hertz
曲率修正（π/4）、C06 Lamé 厚壁筒 hoop stress、C07 parametric pre-strain sweep（找
最小可行 pre-strain 與 2× 製程目標）。**關鍵工程發現：**

- **C04 bond peel：margin = −0.893（fail）**。偏心力矩模型顯示 rib collar tab 與
  spar tube 的 peel load 約 3,740 N/m，遠超過估算允許值 400 N/m。Step 1 的 margin
  2.57（用 0.20 fraction proxy）低估了 peel eccentricity。這是真實工程發現，不是
  程式錯誤；rigid adherend 模型可能偏保守（collar 撓性、adhesive fillet 未計入），
  但在 Step 4 margin 宣稱之前必須先做 **C04 物理 coupon 試驗**。
- **C07 skin sag：nominal margin 0.026**，min viable pre-strain 約 0.05%，
  process target（2×）約 0.10%。製程規格（覆膜收縮協定、預緊量、
  代表性 0.30 m bay panel 試驗）仍是未關閉事項。
- C01/C02/C03/C05/C06 analytical margins 均大（>100），在 HPA 超輕載荷下不是
  governing failure modes。

Step 2 verdict：`step2_analytical_concern_review_needed`（因 C04 為 negative margin）。
輸出位於 `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.json`
與 `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md`。
12 個 tests 通過（24/24 兩個 Step 合計）。

**Step 3 — C04 架構修正方向確立 + collar joint 設計搜尋（2026-05-12）：**
Step 2 eccentric moment model 顯示 C04 問題的根本原因是**偏心力臂**（M = F × r_spar ≈ 0.050 m），
不是 adhesive 強度不足。`scripts/collar_joint_modes.py`（Strategy Pattern library，5 種 collar joint
mode：PeelBond、LoadLineYoke、FrictionClamp、ExternalShearKey、SaddleRingYoke，59 unit tests）與
`scripts/current_pathfinder_rib_collar_joint_design_search.py`（multi-mode design search，11 integration
tests）已把設計搜尋結果確立如下：
- **peel bond（現有構型）**：margin < 0，fail；bondline 需 > 50 mm 才 viable，超出幾何可行範圍
- **load-line yoke**：viable 但需 r_eff < 20 mm；在現有翼肋幾何下可行性偏緊
- **friction clamp**：N_c < 2000 N 即 viable；split clamp 構型幾何上可直接實施
- **external shear key**：兩片合計面積 < 500 mm² 即 viable；輕量替代方案
- **saddle ring yoke（推薦架構）**：conformal bonded ring 繞 spar OD + 一對切向 lug，消除
  outward peel moment；governing mode 改為 lug foot adhesive shear（不是 peel）；fast-model
  估算 pass，recommended fix = `HybridJoint(SaddleRingYoke + FrictionClamp)`

推薦 fix 見 `collar_joint_modes.py::recommended_c04_fix()`。這仍是 analytical / fast-model 估算，
不是 coupon test 或 FEM 簽核；C04 物理 coupon 仍是 Step 4 margin sign-off 的先決條件。

**3 m 翼板運輸接頭設計（2026-05-12）：**
`scripts/current_pathfinder_spar_splice_design.py` 針對 Step-1 freeze 的 structural half-span
`16.5 m`，在 3 m 翼板限制下設計 5 個 splice joints（y = 3 / 6 / 9 / 12 / 15 m），
全翼展共 10 個。接頭採用 CFRP internal spigot（4D overlap each side）+ external ferrule +
shear dog（承 torsion，不鑽穿主管壁）。注意：aero closure / materialized rib station grid
仍可延伸到約 `17.3 m`；splice report 與本段敘事以 structural freeze `16.5 m` 為準。
設計摘要（13 tests pass）：
- 所有接頭 pass，worst margin > 0
- y = 3 m 最重站：factored bending moment 4,437 N·m，spigot wall 自動 upsize 至 1.02 mm
  （預設 0.8 mm 不足）
- torsion margin 全站 >> 1（shear dog 設計遠超 torsion 需求）
- 全翼展接頭總質量 **3.85 kg**，在 HPA 文獻 2.5–6 kg 範圍內
- 3 m 翼板限制確認鎖定：台灣自有貨車（普通小型車駕照 → GVW ≤ 3,500 kg → 貨台 2.7–3 m）
  與空運標準件限制雙重收斂；日本競賽可用 6 噸貨車，但 3 m 更保守

**Step 4 — P1 local load-path closure + mass-integrated pathfinder update（2026-05-12）：**
`scripts/current_pathfinder_p1_load_path_mass_closure.py` 把 Step 2 C04 fail evidence、Step 3
saddle-ring/yoke/clamp fix、3 m spar-splice mass 與 current closure basis 接成同一個
screening runner。輸出位於
`docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md` 與
`output/current_pathfinder_p1_load_path_mass_closure/`。final verdict 是
`p1_local_load_path_ready_for_coupon_fem`：

- baseline C04 eccentric peel margin `-0.893` 保留為現有 peel path fail；installed fix
  `saddle_ring_yoke_plus_secondary_clamp` 轉成 tangential lug / saddle ring load path 後 local
  surrogate pass。governing mode 是 secondary clamp torque，margin `0.8876`；saddle ring yoke
  adhesive shear margin `65.0672`。
- C04 fix mass `0.093839 kg` 與 spar-splice mass `3.847 kg` 已回灌 mass / CG / tail /
  closure。updated screening mass basis `106.828608 kg`；uncompensated CG `0.780039 m`
  明確 rejected，managed final CG `0.75 m` 需要 `0.057304 m` forward rebalance on 56 kg
  equivalent mass。
- tail trim/stability 仍 pass；updated bounded physical twist `1.906952 deg`，root bending
  ratio `0.971590`，closure verdict 仍是 `ready_for_fem_apdl_loadcase_package`。direct
  spar-pair stress-test 超過 3 deg 是 conservative mapping warning，不是 qualified
  aero-surface twist。
- QPROP/XROTOR 是獨立 propulsion lane，不用於 P1 structural blocker pass/fail。

工程邊界：這代表 P1 selected rib/torsion candidate 的 C04 load path 可以進 coupon/local
FEM；不是 final adhesive allowables、laminate buckling、tail hardware、splice production
detail 或 aircraft sign-off。下一步優先是 saddle-ring/yoke coupon + local FEM、secondary
clamp preload/friction protocol、lug/bond fillet detail，以及 C07 skin sag process coupon。

**Baseline A team release system 已建立（2026-05-12）：**
`scripts/build_baseline_a_release.py` 會把目前 P1 mass-integrated closure source 收成
`output/baseline_A_team_release/`。release verdict 是
`baseline_A_release_system_ready`，輸出 geometry freeze、mass budget、CG summary、
drag/power budget、tail/trim/stability summary、structure/control/propulsion interface packs、
manufacturing test plan、carbon tube RFQ screening spec、change-control rules 和 team work
packages。這是把 current pathfinder 轉成可交付、可分工、可重跑、可審核的 team release
package；它不新增物理功能，也不能被解讀成 final aircraft sign-off。AI work-order protocol
位於 `docs/AI_WORK_ORDER_PROTOCOL.md`，priority queue 位於 `docs/work_orders/QUEUE.md`。

**WO-002 — Baseline A mass / CG / margin ledger 已建立（2026-05-12）：**
`scripts/build_baseline_a_release.py` 現在會在同一個 release package 內輸出
`mass_budget.csv`、`cg_summary.json`、`margin_budget.md` 與
`mass_cg_margin_daily_review.md`。ledger verdict 是
`mass_cg_margin_ledger_ready`：gross screening mass `106.828608 kg`、computed
uncompensated CG `0.780039 m` 仍 `explicitly_rejected`、managed CG `0.75 m` 與
required forward rebalance `0.057304 m` 保留；C04 original peel margin `-0.893` 與
installed saddle/yoke/clamp governing margin `0.8876` 同時可見。所有目前 component
mass rows 都是 `estimate` confidence，不能被讀成 measured/frozen weight-and-balance；
QPROP/XROTOR 仍是獨立 propulsion lane，不參與 C04 / rib structural blocker verdict。

**WO-003 — Baseline A design-space freeze audit 已完成（2026-05-12）：**
審核 artifact 位於
`output/baseline_A_team_release/design_space_freeze_audit/`，verdict 是
`baseline_A_freeze_reasonable`。結論是目前沒有 nearby manufacturable candidate 明確觸發
Baseline A reopen：最佳 nearby fast-model row 約省 `4.63%` crank power，低於 5-8%
power reopen trigger，而且沒有 current downstream geometry / CG / torsion / splice /
P1 load-path chain。重要 watch item 是 release mass + tail CD0 charge 丟回 Stage-0
quick-screen 時約有 `-9 W` margin；這要在 WO-006 / WO-007 / WO-008 繼續收斂，不能被讀成
final mission sign-off，也還不是 explicit reopen evidence。

**WO-004 — Manufacturable smoothness / discretization audit 已完成（2026-05-12）：**
審核 artifact 位於
`output/baseline_A_team_release/manufacturable_geometry_audit/`，verdict 是
`geometry_freeze_needs_fix`。工程判讀是 Baseline A smooth pathfinder 沒有大型外形不連續或
explicit reopen trigger，可繼續作 team-release engineering basis；但連續尺寸尚未達到
shop/RFQ drawing control。下一步 WO-005 必須補 controlled station/span/splice manifest，
明確處理 `0.30 m` release rib basis 與 selected stiffness row `0.345 m` label、3 m splice
grid 與 materialized spar-joint rib station、structural `16.5 m` half-span 與 aero/rib
station extent、airfoil/control/transition station contract，以及 inboard splice near-zero
bending margin 的 vendor/RFQ warning。這些是 manufacturability/RFQ gate，不是目前 Baseline A
reopen 或 final aircraft sign-off。

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
  - `scripts/tail_aware_aeroelastic_closure.py`
  - `docs/reports/2026-05-09_tail_aware_aeroelastic_closure.md`
  - `scripts/current_pathfinder_materialized_rib_contract_audit.py`
  - `docs/reports/2026-05-09_current_pathfinder_materialized_rib_contract_audit.md`
  - `scripts/current_pathfinder_rib_torsion_rework_verdict.py`
  - `docs/reports/2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md`
  - `scripts/current_pathfinder_rib_torsion_design_search.py`
  - `docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md`
  - `scripts/current_pathfinder_rib_torsion_fem_calibration.py`
  - `docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md`
  - `docs/reports/2026-05-10_current_pathfinder_rib_torsion_local_validation_shortlist.md`
  - `scripts/current_pathfinder_positive_torque_zone_validation_package.py`
  - `docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md`
  - `scripts/current_pathfinder_rib_local_detail_geometry_freeze.py`
  - `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md`
  - `scripts/current_pathfinder_rib_local_detail_margin_run.py`
  - `docs/reports/2026-05-11_current_pathfinder_rib_local_detail_margin_run.md`
  - `scripts/current_pathfinder_p1_load_path_mass_closure.py`
  - `docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md`
- 角色：把 committed tail/CG basis、physical rib station basis、rear-spar participation、
  warping knockdown、mass/CG bookkeeping 與 closure ranking 接成 tail-aware aeroelastic
  screening basis，並把 current pathfinder 的 rib station / bay / missing contract / skin sag /
  bond-collar / local FEM trigger materialize 成下一輪 hybrid rework 的前置 audit，再把
  candidate trade / closure rerun boundary / FEM package blockers 輸出成可重跑 verdict。
- 注意：rib/rear-spar sensitivity verdict 是 `ready_for_tail_aware_aeroelastic_closure`；
  material-family verdict 是 `foam_only_families_do_not_clear_current_aeroelastic_closure`；
  twist-source verdict 是 `ready_for_hybrid_rib_stiffness_rework`。closure baseline verdict 是
  `needs_aeroelastic_geometry_or_stiffness_rework`，但 rework verdict 已讓 selected hybrid
  basis 進入 closure-owned stiffness model。final CG managed row `0.75 m` 保留；
  早期未補償 tail+ribs mass CG 約 `0.801 m` 的警告不能靜音；P1 mass-integrated closure
  已把 tail/rib/C04 fix/splice mass 一起 charge，updated uncompensated CG `0.780039 m`
  仍 explicitly rejected，只能使用 managed final CG `0.75 m` row。direct spar-pair rotation -> AVL incidence
  目前只是 stress-test proxy，不是 qualified aero-surface twist；foam-only ribs cannot be used
  to claim the current closure blocker is solved。materialized rib audit 只確認 `121` stations /
  `120` bays 與 max bay `0.297063 m`，但 transport/control/airfoil/twist transition、
  skin sag、bond/collar/spar contact 和 torque-critical local FEM 仍是 blocked / needs-data。
  rework verdict 選出 `eps_balsa_cap_hybrid_10mm + bounded_65pct_screening` 作為 local
  FEM/coupon candidate；actual closure-owned hybrid rerun bounded physical twist 是
  `2.070 deg`，direct stress-test 是 `3.449 deg` 並保留為 conservative mapping warning。
  fast design-search loop 會掃 material / thickness / spacing / local reinforcement /
  rear participation 的 candidates，並把 selected fast row 送回 tail-aware closure rerun。
  目前 revised fast-loop selected row 是 10 mm uniform `0.30 m` carbon-collar/rear75，
  bounded twist `1.673592 deg`；CCX local-frame alignment verdict 是
  `fast_physical_model_verified_within_5pct`，代表 structural rows 的 revised fast-vs-CCX
  error 已壓到 `<=5%`，但 carbon/glass collar、bond/tube-wall、skin sag、buckling 仍不是
  final FEM truth。detailed local validation shortlist 已鎖 P1 selected row、P2 12 mm
  carbon-collar reserve、P3 10 mm glass-face collar manufacturability fallback；它只表示
  `selected_candidate_ready_for_detailed_local_validation`。
  positive y≈`2.328 m` local package 已建立：R067/R068/R069、B066-B069、R066/R070
  boundary、APDL guarded skeleton、coupon matrix 和 missing-data register 都已輸出；Step 4
  P1 closure 顯示 C04 saddle-ring/yoke/clamp load path 可以進 coupon/local FEM，且 collar/splice
  mass 已回灌到 closure。這仍不是 FEM signoff：transition/control station、C07 skin sag
  process、local FEM/coupon、hardware/laminate detail 還沒關。

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

### I. Collar joint analysis / C04 fix

- 入口：
  - `scripts/collar_joint_modes.py`（Strategy Pattern library：PeelBond、LoadLineYoke、
    FrictionClamp、ExternalShearKey、SaddleRingYoke + recommended_c04_fix()）
  - `scripts/current_pathfinder_rib_collar_joint_design_search.py`
- 角色：對 y≈2.328 m rib-to-spar collar joint 做多模式設計搜尋，識別 C04 bond peel 的架構修正
  方向；讀入 Step 1 freeze JSON，對 5 種 joint mode 執行 margin sweep 並輸出推薦構型。
- 注意：C04 現有 peel bond 構型 margin = −0.893（fail）；推薦架構為 saddle ring yoke + friction
  clamp，fast-model 估算 pass。P1 mass-integrated closure runner 已消耗這個 fix 並給出
  `p1_local_load_path_ready_for_coupon_fem`。59 unit tests + 11 integration tests pass。
  這是 analytical screening + local surrogate，不是 coupon test 或 FEM 簽核。

### J. 3 m 翼板 spar splice design

- 入口：`scripts/current_pathfinder_spar_splice_design.py`
- 角色：針對 Step-1 freeze structural half-span `16.5 m` 設計 3 m 翼板接頭（5 joints per
  half-wing，10 full-wing），採用 CFRP spigot + ferrule + shear dog，自動 upsize spigot wall，
  輸出 JSON + Markdown + CSV 接頭設計報告。不要把這裡的 16.5 m 與 aero closure /
  materialized rib station grid 的約 17.3 m station extent 混寫。
- 注意：所有接頭 pass，全翼展接頭質量 3.85 kg，y = 3 m 需自動 upsize spigot wall 至 1.02 mm。
  翼板 3 m 限制確認鎖定（台灣自有貨車 + 空運雙重限制）。13 tests pass。

### K. P1 load-path + mass-integrated closure

- 入口：
  - `scripts/current_pathfinder_p1_load_path_mass_closure.py`
  - `docs/reports/2026-05-12_current_pathfinder_p1_load_path_mass_closure.md`
  - `output/current_pathfinder_p1_load_path_mass_closure/`
- 角色：把 P1 C04 saddle-ring/yoke/clamp fix、3 m spar-splice mass、collar-fix mass、
  current closure basis、CG rebalance、tail trim/stability 和 calibrated fast-model boundary
  放進同一個可重跑 verdict。
- 注意：final verdict 是 `p1_local_load_path_ready_for_coupon_fem`。C04 可以進 coupon/local FEM；
  QPROP/XROTOR 是獨立 propulsion lane，不參與 structural blocker 判定。這不是 final adhesive、
  laminate、buckling、tail hardware、splice production detail 或 aircraft sign-off。

### L. Baseline A team release / AI work-order queue

- 入口：
  - `scripts/build_baseline_a_release.py`
  - `output/baseline_A_team_release/`
  - `docs/AI_WORK_ORDER_PROTOCOL.md`
  - `docs/work_orders/QUEUE.md`
  - `docs/work_orders/templates/work_order_template.md`
- 角色：把 current pathfinder / Baseline A 變成 team release package，讓施工、結構、控制、
  傳動、製造組能從同一組 freeze / interface / change-control artifacts 開始工作；同時讓
  後續 AI thread 依 priority queue 自動挑任務、驗證、更新文件、commit，並產生 reviewer prompt。
- 注意：release verdict 是 `baseline_A_release_system_ready`，不是 final aircraft sign-off。
  P1 仍只到 coupon/local FEM readiness；C04 fix 是 architecture-selected but coupon/local FEM
  pending；QPROP/XROTOR 保持 independent propulsion lane；大型 SU2、NSGA、propeller
  optimization、random disturbance simulator、full CAD automation 只進 queue，不在 release
  builder 任務中實作。WO-003 design-space freeze audit 的 verdict 是
  `baseline_A_freeze_reasonable`；WO-004 manufacturable geometry audit 的 verdict 是
  `geometry_freeze_needs_fix`，表示 release engineering 可繼續，但 RFQ/shop 前要補
  controlled station/span/splice manifest。下一個 P0 是 WO-005 carbon tube RFQ pack。

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
- 把 QPROP/XROTOR propulsion sizing 混入 P1 C04 structural blocker 判定；它們只能是獨立
  propulsion lane。
- 把 `birdman_mission_coupled_medium_search_20260503`、`sample_1476`、`233 W`、`8642.9 m`
  當成 current mission evidence。
- 把舊的一維、舊 CFRP、legacy refresh、研究型 script output 當成目前 pathfinder 的 production truth。

## 10. 對未來 AI Agent 的工作規則

1. 先讀這份 `CURRENT_MAINLINE.md`，再讀 `README.md`。接 Baseline A team work 時，再讀
   `docs/AI_WORK_ORDER_PROTOCOL.md`、`docs/work_orders/QUEUE.md` 與
   `output/baseline_A_team_release/`。
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
